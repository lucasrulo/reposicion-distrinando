"""
Extractor de ventas + stock para el Dashboard de Reposición (Distrinando).

Usa GraphQL Bulk Operations (1 operación de órdenes + 1 de variantes por tienda),
así que no importa el volumen: Shopify arma el archivo y lo bajamos de una.

Genera en ./data:
  ventas_diarias.parquet   -> fecha, marca, tienda, sku, unidades, venta_neta  (últimos DIAS_HISTORIA días)
  stock_actual.parquet     -> 1 fila por SKU x ubicación con disponible/entrante/comprometido + catálogo
  stock_historial.parquet  -> snapshot diario de disponible por SKU (se acumula; sirve para
                              descontar los días sin stock al calcular la velocidad de venta)
  meta.json                -> fecha de la última corrida y estado por tienda
"""
import io
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

# ==============================================================================
# CONFIG
# ==============================================================================
API_VERSION = "2026-07"          # subirla cada ~3-4 meses
DIAS_HISTORIA = 180              # ventana de ventas que se descarga en cada corrida
DIAS_HISTORIAL_STOCK = 400       # cuánto historial de snapshots de stock se conserva
DATA_DIR = os.environ.get("DATA_DIR", "data")
ZONA_AR = timezone(timedelta(hours=-3))

# Tiendas (mismos secrets que el dashboard de ventas).
# "vendors" mapea vendor de Shopify -> marca, para tiendas compartidas (Columbia + MHW + Sorel).
STORES = {
    "Reebok":     {"url": "reebok-ar",     "secret": "TOKEN_REEBOK"},
    "Columbia":   {"url": "columbia-ar",   "secret": "TOKEN_COLUMBIA",
                   "vendors": {"MHW-ar": "Mountain Hardwear", "Sorel-ar": "Sorel"}},
    "Crocs":      {"url": "crocs-ar",      "secret": "TOKEN_CROCS"},
    "Kappa":      {"url": "kappa-ar",      "secret": "TOKEN_KAPPA"},
    "Piccadilly": {"url": "piccadilly-ar", "secret": "TOKEN_PICCADILLY"},
}

OPCIONES_COLOR = {"color", "colour", "colores"}
OPCIONES_TALLE = {"talle", "talla", "size", "tamaño", "medida", "número", "numero"}


def obtener_token(nombre):
    tok = os.environ.get(nombre)
    if tok:
        return tok
    try:
        from streamlit import secrets
        return secrets.get(nombre)
    except Exception:
        return None


# ==============================================================================
# QUERIES (validadas contra el schema Admin)
# ==============================================================================
Q_ORDERS = """
{
  orders(query: "created_at:>=%s") {
    edges { node {
      id createdAt cancelledAt test
      lineItems { edges { node {
        id sku quantity currentQuantity vendor
        discountedUnitPriceAfterAllDiscountsSet { shopMoney { amount } }
        originalUnitPriceSet { shopMoney { amount } }
      } } }
    } }
  }
}
"""

Q_VARIANTS = """
{
  productVariants {
    edges { node {
      id sku title price compareAtPrice
      selectedOptions { name value }
      product {
        id title handle vendor productType status createdAt
        featuredMedia { preview { image { url } } }
      }
      inventoryItem {
        id tracked
        unitCost { amount }
        inventoryLevels { edges { node {
          id
          item { id }
          location { id name }
          quantities(names: ["available", "incoming", "committed", "on_hand"]) { name quantity }
        } } }
      }
    } }
  }
}
"""

M_RUN = """
mutation RunBulk($q: String!) {
  bulkOperationRunQuery(query: $q) {
    bulkOperation { id status }
    userErrors { field message }
  }
}
"""

Q_POLL = """
query Poll($id: ID!) {
  node(id: $id) { ... on BulkOperation { id status errorCode objectCount url partialDataUrl } }
}
"""

# Versiones mínimas (si la app no tiene algún permiso para los campos "lindos")
Q_ORDERS_MIN = """
{
  orders(query: "created_at:>=%s") {
    edges { node {
      id createdAt cancelledAt
      lineItems { edges { node {
        id sku quantity currentQuantity
        originalUnitPriceSet { shopMoney { amount } }
      } } }
    } }
  }
}
"""

Q_VARIANTS_MIN = """
{
  productVariants {
    edges { node {
      id sku title %s
      selectedOptions { name value }
      product { id title handle vendor productType status createdAt }
      inventoryItem {
        id tracked
        inventoryLevels { edges { node {
          id
          item { id }
          location { id name }
          quantities(names: ["available", "on_hand"]) { name quantity }
        } } }
      }
    } }
  }
}
"""

Q_VARIANTS_SIN_UBIC = """
{
  productVariants {
    edges { node {
      id sku title price compareAtPrice
      selectedOptions { name value }
      product {
        id title handle vendor productType status createdAt
        featuredMedia { preview { image { url } } }
      }
      inventoryItem {
        id tracked
        unitCost { amount }
        inventoryLevels { edges { node {
          id
          item { id }
          quantities(names: ["available", "incoming", "committed", "on_hand"]) { name quantity }
        } } }
      }
    } }
  }
}
"""

Q_SCOPES = "{ currentAppInstallation { accessScopes { handle } } }"

Q_CURRENT = "{ currentBulkOperation { id status } }"
M_CANCEL = "mutation($id: ID!) { bulkOperationCancel(id: $id) { userErrors { message } } }"


class BulkError(RuntimeError):
    def __init__(self, status, code):
        super().__init__(f"bulk {status} ({code})")
        self.code = code


# ==============================================================================
# CLIENTE
# ==============================================================================
class Shopify:
    def __init__(self, nombre, url, token):
        self.nombre = nombre
        self.endpoint = f"https://{url}.myshopify.com/admin/api/{API_VERSION}/graphql.json"
        self.headers = {"X-Shopify-Access-Token": token, "Content-Type": "application/json"}
        self.store_url = f"https://{url}.myshopify.com"

    def gql(self, query, variables=None, intentos=5):
        for i in range(intentos):
            r = requests.post(self.endpoint, headers=self.headers,
                              json={"query": query, "variables": variables or {}}, timeout=60)
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(2 ** i)
                continue
            if r.status_code != 200:
                raise RuntimeError(f"{self.nombre}: HTTP {r.status_code} -> {r.text[:300]}")
            body = r.json()
            if body.get("errors"):
                if any(e.get("extensions", {}).get("code") == "THROTTLED" for e in body["errors"]):
                    time.sleep(2 ** i)
                    continue
                raise RuntimeError(f"{self.nombre}: GraphQL errors -> {body['errors']}")
            return body["data"]
        raise RuntimeError(f"{self.nombre}: sin respuesta tras {intentos} intentos")

    def bulk(self, query, timeout_s=1500):
        """Lanza una bulk operation, espera y devuelve la lista de objetos JSONL."""
        # Si quedó una corriendo de una corrida anterior, la cancelamos.
        cur = self.gql(Q_CURRENT).get("currentBulkOperation")
        if cur and cur["status"] in ("CREATED", "RUNNING"):
            self.gql(M_CANCEL, {"id": cur["id"]})
            time.sleep(5)

        data = self.gql(M_RUN, {"q": query})["bulkOperationRunQuery"]
        if data["userErrors"]:
            raise RuntimeError(f"{self.nombre}: {data['userErrors']}")
        op_id = data["bulkOperation"]["id"]

        t0, espera = time.time(), 3
        while True:
            op = self.gql(Q_POLL, {"id": op_id})["node"]
            st = op["status"]
            if st == "COMPLETED":
                break
            if st in ("FAILED", "CANCELED", "EXPIRED"):
                raise BulkError(st, op.get("errorCode"))
            if time.time() - t0 > timeout_s:
                raise RuntimeError(f"{self.nombre}: bulk timeout")
            time.sleep(espera)
            espera = min(espera * 1.5, 20)

        url = op.get("url") or op.get("partialDataUrl")
        if not url:  # 0 objetos
            return []
        r = requests.get(url, timeout=300)
        r.raise_for_status()
        return [json.loads(l) for l in r.text.splitlines() if l.strip()]


# ==============================================================================
# PARSEO
# ==============================================================================
def _money(obj, *path):
    try:
        for p in path:
            obj = obj[p]
        return float(obj)
    except Exception:
        return None


def parsear_ventas(objs, marca_tienda, vendors_map):
    ordenes, lineas = {}, []
    for o in objs:
        gid = o.get("id", "")
        if "/Order/" in gid:
            ordenes[gid] = o
        elif "/LineItem/" in gid:
            lineas.append(o)

    filas = []
    for li in lineas:
        o = ordenes.get(li.get("__parentId"))
        if not o or o.get("test") or o.get("cancelledAt"):
            continue
        qty = li.get("currentQuantity")
        qty = li.get("quantity", 0) if qty is None else qty   # currentQuantity descuenta devoluciones/ediciones
        if not qty:
            continue
        precio = _money(li, "discountedUnitPriceAfterAllDiscountsSet", "shopMoney", "amount")
        if precio is None:
            precio = _money(li, "originalUnitPriceSet", "shopMoney", "amount") or 0.0
        fecha = datetime.fromisoformat(o["createdAt"].replace("Z", "+00:00")).astimezone(ZONA_AR).date()
        filas.append({
            "fecha": fecha,
            "tienda": marca_tienda,
            "marca": vendors_map.get(li.get("vendor") or "", marca_tienda),
            "sku": (li.get("sku") or "").strip() or "S/D",
            "unidades": int(qty),
            "venta_neta": float(precio) * int(qty),
        })
    df = pd.DataFrame(filas)
    if df.empty:
        return df
    return df.groupby(["fecha", "tienda", "marca", "sku"], as_index=False)[["unidades", "venta_neta"]].sum()


def parsear_stock(objs, marca_tienda, vendors_map, store_url):
    variantes, niveles = {}, []
    for o in objs:
        gid = o.get("id", "")
        if "/ProductVariant/" in gid:
            variantes[o["inventoryItem"]["id"] if o.get("inventoryItem") else gid] = o
        elif "/InventoryLevel/" in gid:
            niveles.append(o)

    # Agrupamos niveles por inventoryItem
    por_item = {}
    for n in niveles:
        item_id = (n.get("item") or {}).get("id") or n.get("__parentId")
        q = {x["name"]: x["quantity"] for x in n.get("quantities", [])}
        por_item.setdefault(item_id, []).append({
            "ubicacion": (n.get("location") or {}).get("name", "Todas las ubicaciones"),
            "disponible": q.get("available", 0),
            "entrante": q.get("incoming", 0),
            "comprometido": q.get("committed", 0),
            "en_mano": q.get("on_hand", 0),
        })

    filas = []
    for item_id, v in variantes.items():
        p = v.get("product") or {}
        opts = {(o["name"] or "").strip().lower(): o["value"] for o in v.get("selectedOptions", [])}
        color = next((val for k, val in opts.items() if k in OPCIONES_COLOR), "")
        talle = next((val for k, val in opts.items() if k in OPCIONES_TALLE), "")
        sku = (v.get("sku") or "").strip()
        if not talle and "-" in sku:
            talle = sku.rsplit("-", 1)[1]
        img = (((p.get("featuredMedia") or {}).get("preview") or {}).get("image") or {}).get("url", "")
        base = {
            "tienda": marca_tienda,
            "marca": vendors_map.get(p.get("vendor") or "", marca_tienda),
            "sku": sku or "S/D",
            "variant_id": v["id"],
            "producto": p.get("title", ""),
            "handle": p.get("handle", ""),
            "tipo": p.get("productType", ""),
            "estado": p.get("status", ""),
            "creado": (p.get("createdAt") or "")[:10],
            "color": color,
            "talle": talle,
            "precio": float(v.get("price") or 0),
            "precio_lista": float(v.get("compareAtPrice") or 0) or None,
            "costo": _money(v, "inventoryItem", "unitCost", "amount"),
            "trackeado": bool((v.get("inventoryItem") or {}).get("tracked", True)),
            "img_url": img,
            "url_admin": f"{store_url}/admin/products/{p.get('id', '').split('/')[-1]}",
        }
        locs = por_item.get(item_id) or [{"ubicacion": "(sin ubicación)", "disponible": 0,
                                          "entrante": 0, "comprometido": 0, "en_mano": 0}]
        for l in locs:
            filas.append({**base, **l})
    return pd.DataFrame(filas)


# ==============================================================================
# PERSISTENCIA
# ==============================================================================
def _leer(nombre):
    path = os.path.join(DATA_DIR, nombre)
    return pd.read_parquet(path) if os.path.exists(path) else pd.DataFrame()


def _guardar(df, nombre):
    os.makedirs(DATA_DIR, exist_ok=True)
    df.to_parquet(os.path.join(DATA_DIR, nombre), index=False)


def main():
    ahora = datetime.now(ZONA_AR)
    desde = (ahora - timedelta(days=DIAS_HISTORIA)).strftime("%Y-%m-%d")
    print(f"--- SYNC {ahora:%Y-%m-%d %H:%M} ARG | ventas desde {desde} ---")

    ventas_old = _leer("ventas_diarias.parquet")
    stock_old = _leer("stock_actual.parquet")
    ventas, stock, estado = [], [], {}

    for tienda, cfg in STORES.items():
        token = obtener_token(cfg["secret"])
        if not token:
            estado[tienda] = "sin token"
            print(f"  ⏭️  {tienda}: sin token")
            print(f"::warning::{tienda}: falta el secret {cfg['secret']} (o está vacío)")
            continue
        cli = Shopify(tienda, cfg["url"], token)
        vmap = cfg.get("vendors", {})
        t = time.time()
        # --- permisos de la app ---
        try:
            scopes = {x["handle"] for x in cli.gql(Q_SCOPES)["currentAppInstallation"]["accessScopes"]}
            scopes |= {x.replace("write_", "read_") for x in scopes}
            print(f"  🔑 {tienda}: permisos -> {', '.join(sorted(x for x in scopes if x.startswith('read_')))}")
            faltan = [x for x in ("read_orders", "read_products", "read_inventory", "read_locations") if x not in scopes]
            if faltan:
                print(f"::warning::{tienda}: a la app le faltan permisos {faltan}")
        except Exception as e:
            scopes = None
            print(f"::warning::{tienda}: no pude leer los permisos ({e})")

        dias = DIAS_HISTORIA
        if scopes is not None and "read_all_orders" not in scopes:
            dias = 59
            print(f"::warning::{tienda}: sin permiso read_all_orders -> solo se bajan {dias} días de ventas")
        desde_t = (ahora - timedelta(days=dias)).strftime("%Y-%m-%d")

        # --- STOCK (imprescindible) ---
        ds = None
        intentos_stock = [("completa", Q_VARIANTS), ("sin ubicaciones", Q_VARIANTS_SIN_UBIC),
                          ("sin costo/imagen", Q_VARIANTS_MIN % "price"), ("mínima", Q_VARIANTS_MIN % "")]
        if scopes is not None and "read_locations" not in scopes:
            print(f"::warning::{tienda}: sin permiso read_locations -> stock total, sin detalle por ubicación")
            intentos_stock = [("sin ubicaciones", Q_VARIANTS_SIN_UBIC)]
        for nombre_q, q in intentos_stock:
            try:
                ds = parsear_stock(cli.bulk(q), tienda, vmap, cli.store_url)
                if nombre_q != "completa":
                    print(f"::warning::{tienda}: stock bajado con consulta {nombre_q} (faltan permisos para costo/imagen/precio)")
                break
            except BulkError as e:
                print(f"  ⚠️  {tienda}: stock con consulta {nombre_q} falló: {e}")
                if e.code != "ACCESS_DENIED":
                    break
            except Exception as e:
                print(f"  ⚠️  {tienda}: stock con consulta {nombre_q} falló: {e}")
                break

        # --- VENTAS ---
        dv = None
        intentos = [("completa", Q_ORDERS % desde_t), ("mínima", Q_ORDERS_MIN % desde_t)]
        if dias > 59:
            d59 = (ahora - timedelta(days=59)).strftime("%Y-%m-%d")
            intentos.insert(1, ("completa 59 días", Q_ORDERS % d59))
            intentos.append(("mínima 59 días", Q_ORDERS_MIN % d59))
        for nombre_q, q in intentos:
            try:
                dv = parsear_ventas(cli.bulk(q), tienda, vmap)
                if nombre_q != "completa":
                    print(f"::warning::{tienda}: ventas bajadas con consulta {nombre_q}")
                break
            except BulkError as e:
                print(f"  ⚠️  {tienda}: ventas con consulta {nombre_q} falló: {e}")
                if e.code != "ACCESS_DENIED":
                    break
            except Exception as e:
                print(f"  ⚠️  {tienda}: ventas con consulta {nombre_q} falló: {e}")
                break

        if ds is not None and not ds.empty:
            stock.append(ds)
        elif not stock_old.empty:
            stock.append(stock_old[stock_old["tienda"] == tienda])
        if dv is not None:
            ventas.append(dv)
        elif not ventas_old.empty:
            ventas.append(ventas_old[ventas_old["tienda"] == tienda])

        if ds is None:
            estado[tienda] = "error: no se pudo leer el stock"
            print(f"::error::{tienda}: no se pudo leer el stock (ver líneas ⚠️ del log)")
        elif dv is None:
            estado[tienda] = "parcial: stock ok, ventas con error"
            print(f"::error::{tienda}: stock OK pero no se pudieron leer las ventas (ver líneas ⚠️ del log)")
        else:
            estado[tienda] = "ok"
        print(f"  {'✅' if estado[tienda] == 'ok' else '⚠️'} {tienda}: "
              f"{int(dv['unidades'].sum()) if dv is not None and not dv.empty else 0} uds vendidas, "
              f"{ds['sku'].nunique() if ds is not None and not ds.empty else 0} SKUs ({time.time() - t:.0f}s)")

    df_v = pd.concat([d for d in ventas if not d.empty], ignore_index=True) if ventas else pd.DataFrame()
    df_s = pd.concat([d for d in stock if not d.empty], ignore_index=True) if stock else pd.DataFrame()
    if df_s.empty:
        print("🛑 No se obtuvo stock de ninguna tienda. No se pisa nada.")
        print("::error::No se obtuvo stock de ninguna tienda. Revisá los secrets TOKEN_* y los avisos de arriba.")
        sys.exit(1)

    _guardar(df_v, "ventas_diarias.parquet")
    _guardar(df_s, "stock_actual.parquet")

    # Snapshot diario de stock (disponible total por SKU). La corrida más reciente del día pisa la anterior.
    hoy = ahora.date()
    snap = df_s.groupby(["tienda", "marca", "sku"], as_index=False)["disponible"].sum()
    snap["fecha"] = hoy
    hist = _leer("stock_historial.parquet")
    if not hist.empty:
        hist["fecha"] = pd.to_datetime(hist["fecha"]).dt.date
        hist = hist[(hist["fecha"] != hoy) & (hist["fecha"] >= hoy - timedelta(days=DIAS_HISTORIAL_STOCK))]
    hist = pd.concat([hist, snap], ignore_index=True)
    _guardar(hist, "stock_historial.parquet")

    with open(os.path.join(DATA_DIR, "meta.json"), "w") as f:
        json.dump({"actualizado": ahora.isoformat(), "tiendas": estado, "dias_historia": DIAS_HISTORIA}, f,
                  ensure_ascii=False, indent=2)
    print(f"🚀 Listo: {len(df_v):,} filas de ventas | {len(df_s):,} filas de stock | historial {hist['fecha'].nunique()} días")


if __name__ == "__main__":
    main()
