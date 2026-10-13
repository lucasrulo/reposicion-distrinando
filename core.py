"""
Motor de cálculo de reposición. Lo usan app.py (dashboard) y alertas.py (digest por mail).

Lógica por SKU:
  velocidad diaria  = 0.5·v14 + 0.3·v30 + 0.2·v60, donde cada vN = unidades / días con stock en la ventana
                      (se descuentan días quebrados según el historial de snapshots y la antigüedad del producto)
  stock de seguridad= z(nivel de servicio por ABC) · σ demanda diaria · √lead time
  punto de pedido   = velocidad · lead time + stock de seguridad
  stock objetivo    = velocidad · (lead time + cobertura) + stock de seguridad
  sugerido          = objetivo − (disponible + entrante), solo si la posición está en/bajo el punto de pedido
"""
from datetime import date, timedelta
from statistics import NormalDist

import numpy as np
import pandas as pd

PARAMS_DEFAULT = {
    "lead_time": 30,            # días desde que pedís hasta que el stock está disponible en la tienda
    "cobertura": 60,            # días de venta que querés cubrir con cada reposición
    "servicio": {"A": 0.95, "B": 0.90, "C": 0.80},
    "pesos": {14: 0.5, 30: 0.3, 60: 0.2},
    "dias_sobrestock": 180,
    "acelera_ratio": 1.5,       # v7 / v30 por encima de esto = acelerando
    "acelera_min_uds": 3,       # mínimo de unidades en 7 días para considerar aceleración
    "curva_rota_pct": 0.30,     # % de talles con demanda que están sin stock
    "dias_sin_mov": 60,
    "por_marca": {},            # {"Crocs": {"lead_time": 45, "cobertura": 90}, ...}
}

ESTADOS = ["🔴 Quiebre", "🟠 Crítico", "🟡 Reponer", "🧊 Sobrestock", "💤 Sin movimiento", "🟢 OK", "⚪ Sin demanda"]
PRIORIDAD = {e: i for i, e in enumerate(ESTADOS)}

ORDEN_TALLES = ["XXS", "XS", "S", "M", "L", "XL", "XXL", "2XL", "XXXL", "3XL", "4XL", "U", "UNICO", "ÚNICO", "TU"]


def modelo_color(sku: str) -> str:
    sku = str(sku or "")
    return sku.rsplit("-", 1)[0] if "-" in sku else sku


def clave_talle(t):
    s = str(t).strip().upper().replace(",", ".")
    try:
        return (0, float(s.split("/")[0].split("-")[0]), s)
    except ValueError:
        return (1, ORDEN_TALLES.index(s) if s in ORDEN_TALLES else 99, s)


def _abc(valores: pd.Series) -> pd.Series:
    if valores.sum() <= 0:
        return pd.Series("C", index=valores.index)
    orden = valores.sort_values(ascending=False)
    acum = orden.cumsum() / orden.sum()
    clase = pd.Series(np.where(acum <= 0.80, "A", np.where(acum <= 0.95, "B", "C")), index=orden.index)
    clase[orden <= 0] = "C"
    return clase.reindex(valores.index)


def preparar(ventas, stock, hist, ubicaciones=None, incluir_estados=("ACTIVE", "UNLISTED", "DRAFT")):
    """Normaliza tipos y agrega stock por SKU (sumando las ubicaciones elegidas)."""
    v = ventas.copy()
    if not v.empty:
        v["fecha"] = pd.to_datetime(v["fecha"]).dt.normalize()
        v = v[v["sku"] != "S/D"]

    s = stock.copy()
    s = s[s["sku"] != "S/D"]
    if incluir_estados:
        s = s[s["estado"].isin(incluir_estados)]
    if ubicaciones:
        s = s[s["ubicacion"].isin(ubicaciones)]
    cat_cols = ["tienda", "marca", "sku", "producto", "handle", "tipo", "estado", "creado", "color", "talle",
                "precio", "precio_lista", "costo", "trackeado", "img_url", "url_admin"]
    cat = s[cat_cols].drop_duplicates(["tienda", "sku"])
    qty = s.groupby(["tienda", "sku"], as_index=False)[["disponible", "entrante", "comprometido"]].sum()
    s_sku = cat.merge(qty, on=["tienda", "sku"], how="left")

    h = hist.copy()
    if not h.empty:
        h["fecha"] = pd.to_datetime(h["fecha"]).dt.normalize()
    return v, s_sku, h


def calcular_sku(ventas, stock_sku, hist, params=None, hoy=None):
    p = {**PARAMS_DEFAULT, **(params or {})}
    hoy = pd.Timestamp(hoy or date.today()).normalize()
    df = stock_sku.copy()
    key = ["tienda", "sku"]

    # ---------- ventas por ventana ----------
    for n in (7, 14, 30, 60, 90):
        w = ventas[(ventas["fecha"] >= hoy - pd.Timedelta(days=n)) & (ventas["fecha"] < hoy)] if not ventas.empty else ventas
        agg = w.groupby(key)[["unidades", "venta_neta"]].sum() if not w.empty else pd.DataFrame(columns=["unidades", "venta_neta"])
        df = df.merge(agg.rename(columns={"unidades": f"u{n}", "venta_neta": f"vta{n}"}), left_on=key, right_index=True, how="left")
    hoy_v = ventas[ventas["fecha"] >= hoy] if not ventas.empty else ventas
    agg_hoy = hoy_v.groupby(key)["unidades"].sum().rename("u_hoy") if not hoy_v.empty else pd.Series(name="u_hoy", dtype=float)
    df = df.merge(agg_hoy, left_on=key, right_index=True, how="left")
    ult = ventas.groupby(key)["fecha"].max().rename("ultima_venta") if not ventas.empty else pd.Series(name="ultima_venta", dtype="datetime64[ns]")
    df = df.merge(ult, left_on=key, right_index=True, how="left")
    num = [c for c in df.columns if c.startswith(("u", "vta")) and c not in ("ultima_venta", "url_admin")]
    df[num] = df[num].fillna(0)

    # ---------- días con stock por ventana ----------
    creado = pd.to_datetime(df["creado"], errors="coerce").dt.tz_localize(None).dt.normalize()
    dias_vida = (hoy - creado).dt.days.fillna(9999).clip(lower=1)
    sin_stock = {n: pd.Series(0, index=df.index) for n in p["pesos"]}
    if not hist.empty:
        hh = hist[hist["fecha"] < hoy].groupby(key + ["fecha"], as_index=False)["disponible"].sum()
        if not ventas.empty:
            vd = ventas.groupby(key + ["fecha"], as_index=False)["unidades"].sum()
            hh = hh.merge(vd, on=key + ["fecha"], how="left")
        else:
            hh["unidades"] = 0
        hh["quebrado"] = (hh["disponible"] <= 0) & (hh["unidades"].fillna(0) <= 0)
        for n in p["pesos"]:
            c = hh[(hh["fecha"] >= hoy - pd.Timedelta(days=n)) & hh["quebrado"]].groupby(key).size().rename("q")
            sin_stock[n] = df[key].merge(c, left_on=key, right_index=True, how="left")["q"].fillna(0).values
    vel = pd.Series(0.0, index=df.index)
    for n, peso in p["pesos"].items():
        dias = np.minimum(n, dias_vida) - sin_stock[n]
        dias = np.maximum(dias, min(7, n))
        df[f"v{n}"] = df[f"u{n}"] / dias
        vel += peso * df[f"v{n}"]
    df["velocidad"] = vel
    df["v7"] = df["u7"] / np.maximum(np.minimum(7, dias_vida), 1)
    df["tendencia"] = np.where(df["v30"] > 0, df["v7"] / df["v30"], np.where(df["u7"] > 0, 9.99, 0))

    # ---------- σ de demanda diaria (60 días) ----------
    if not ventas.empty:
        w = ventas[(ventas["fecha"] >= hoy - pd.Timedelta(days=60)) & (ventas["fecha"] < hoy)]
        g = w.groupby(key)["unidades"].agg(["sum", lambda x: (x ** 2).sum()])
        g.columns = ["s1", "s2"]
        n = 60
        g["sigma"] = np.sqrt(np.maximum((g["s2"] - g["s1"] ** 2 / n) / (n - 1), 0))
        df = df.merge(g[["sigma"]], left_on=key, right_index=True, how="left")
    else:
        df["sigma"] = 0.0
    df["sigma"] = df["sigma"].fillna(0)

    # ---------- ABC (por facturación 90d dentro de cada marca) ----------
    df["abc"] = df.groupby("marca", group_keys=False)["vta90"].apply(_abc)

    # ---------- parámetros por marca ----------
    lt = df["marca"].map(lambda m: p["por_marca"].get(m, {}).get("lead_time", p["lead_time"]))
    cob = df["marca"].map(lambda m: p["por_marca"].get(m, {}).get("cobertura", p["cobertura"]))
    z = df["abc"].map(lambda c: NormalDist().inv_cdf(p["servicio"].get(c, 0.85)))
    df["lead_time"], df["cobertura_obj"] = lt, cob

    disp = df["disponible"].clip(lower=0)
    df["posicion"] = disp + df["entrante"].clip(lower=0)
    df["stock_seguridad"] = z * df["sigma"] * np.sqrt(lt)
    df["punto_pedido"] = df["velocidad"] * lt + df["stock_seguridad"]
    df["stock_objetivo"] = df["velocidad"] * (lt + cob) + df["stock_seguridad"]
    reponer = (df["velocidad"] > 0) & (df["posicion"] <= df["punto_pedido"])
    df["sugerido"] = np.where(reponer, np.ceil(np.maximum(df["stock_objetivo"] - df["posicion"], 1)), 0).astype(int)
    df["cobertura_dias"] = np.where(df["velocidad"] > 0, disp / df["velocidad"], np.inf)
    df["fecha_quiebre"] = np.where(np.isfinite(df["cobertura_dias"]),
                                   hoy + pd.to_timedelta(np.nan_to_num(df["cobertura_dias"], posinf=0).round(), unit="D"),
                                   pd.NaT)
    df["fecha_quiebre"] = pd.to_datetime(df["fecha_quiebre"])
    df["sell_through_30"] = np.where(df["u30"] + disp > 0, df["u30"] / (df["u30"] + disp), 0)
    df["dias_sin_venta"] = (hoy - df["ultima_venta"]).dt.days
    df["venta_perdida_dia"] = np.where(disp <= 0, df["velocidad"] * df["precio"], 0)
    df["valor_stock"] = disp * df["costo"].fillna(df["precio"])
    df["valor_sugerido"] = df["sugerido"] * df["costo"].fillna(df["precio"])
    df["acelerando"] = (df["tendencia"] >= p["acelera_ratio"]) & (df["u7"] >= p["acelera_min_uds"])
    df["stock_negativo"] = df["disponible"] < 0

    # ---------- estado ----------
    viejo = dias_vida > 30
    cond = [
        (disp <= 0) & (df["velocidad"] > 0),
        (df["velocidad"] > 0) & (df["posicion"] / df["velocidad"].where(df["velocidad"] > 0, 1) < lt),  # se quiebra antes de que llegue una reposición pedida hoy
        reponer,
        (df["velocidad"] > 0) & (df["cobertura_dias"] > p["dias_sobrestock"]),
        (disp > 0) & (df["u60"] == 0) & viejo,
        df["velocidad"] > 0,
    ]
    df["estado_rep"] = np.select(cond, ESTADOS[:6], default=ESTADOS[6])
    df["modelo_color"] = df["sku"].map(modelo_color)
    return df


def calcular_modelo(df_sku, params=None):
    p = {**PARAMS_DEFAULT, **(params or {})}
    d = df_sku.copy()
    d["prio"] = d["estado_rep"].map(PRIORIDAD)
    d["con_demanda"] = d["u90"] > 0
    d["quebrado_dem"] = d["con_demanda"] & (d["disponible"] <= 0)
    g = d.groupby(["tienda", "marca", "modelo_color"])
    m = g.agg(
        producto=("producto", "first"), color=("color", "first"), img_url=("img_url", "first"),
        url_admin=("url_admin", "first"), estado=("estado", "first"), tipo=("tipo", "first"),
        talles=("sku", "count"), talles_con_stock=("disponible", lambda x: int((x > 0).sum())),
        talles_demanda=("con_demanda", "sum"), talles_quebrados_dem=("quebrado_dem", "sum"),
        disponible=("disponible", lambda x: x.clip(lower=0).sum()), entrante=("entrante", "sum"),
        u_hoy=("u_hoy", "sum"), u7=("u7", "sum"), u14=("u14", "sum"), u30=("u30", "sum"), u60=("u60", "sum"), u90=("u90", "sum"),
        vta30=("vta30", "sum"), vta90=("vta90", "sum"),
        velocidad=("velocidad", "sum"), v7=("v7", "sum"), v30=("v30", "sum"),
        sugerido=("sugerido", "sum"), valor_sugerido=("valor_sugerido", "sum"), valor_stock=("valor_stock", "sum"),
        venta_perdida_dia=("venta_perdida_dia", "sum"), precio=("precio", "max"),
        skus_quiebre=("estado_rep", lambda x: int((x == ESTADOS[0]).sum())),
        prio=("prio", "min"), ultima_venta=("ultima_venta", "max"),
    ).reset_index()
    m["estado_rep"] = m["prio"].map(dict(enumerate(ESTADOS)))
    m["cobertura_dias"] = np.where(m["velocidad"] > 0, m["disponible"] / m["velocidad"], np.inf)
    m["curva_pct"] = np.where(m["talles"] > 0, m["talles_con_stock"] / m["talles"], 0)
    m["curva_rota"] = (m["talles_demanda"] > 0) & (m["disponible"] > 0) & \
                      (m["talles_quebrados_dem"] / m["talles_demanda"].clip(lower=1) >= p["curva_rota_pct"])
    m["tendencia"] = np.where(m["v30"] > 0, m["v7"] / m["v30"], np.where(m["u7"] > 0, 9.99, 0))
    m["acelerando"] = (m["tendencia"] >= p["acelera_ratio"]) & (m["u7"] >= p["acelera_min_uds"])
    m["sell_through_30"] = np.where(m["u30"] + m["disponible"] > 0, m["u30"] / (m["u30"] + m["disponible"]), 0)
    m["abc"] = m.groupby("marca", group_keys=False)["vta90"].apply(_abc)
    return m.drop(columns=["prio"])


def resumen_alertas(df_sku, df_mod):
    """Listas de alertas listas para mostrar / mandar por mail."""
    s = df_sku
    return {
        "quiebre": s[s["estado_rep"] == ESTADOS[0]].sort_values("venta_perdida_dia", ascending=False),
        "critico": s[s["estado_rep"] == ESTADOS[1]].sort_values("cobertura_dias"),
        "reponer": s[s["sugerido"] > 0].sort_values(["abc", "cobertura_dias"]),
        "curva_rota": df_mod[df_mod["curva_rota"]].sort_values("vta30", ascending=False),
        "acelerando": df_mod[df_mod["acelerando"]].sort_values("tendencia", ascending=False),
        "sobrestock": s[s["estado_rep"] == ESTADOS[3]].sort_values("valor_stock", ascending=False),
        "sin_movimiento": s[s["estado_rep"] == ESTADOS[4]].sort_values("valor_stock", ascending=False),
        "stock_negativo": s[s["stock_negativo"]],
    }
