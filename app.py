"""
Distrinando | Centro de Reposición
Venta por Modelo+Color → SKU, velocidad, cobertura, alertas y plan de reposición.
Lee los datos que deja el extractor (GitHub Actions) en la rama `data` del repo.
"""
import hashlib
import hmac
import io
import json
import os
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

import core

ZONA_AR = timezone(timedelta(hours=-3))
st.set_page_config(page_title="Distrinando | Reposición", page_icon="📦", layout="wide", initial_sidebar_state="expanded")

try:
    from streamlit_autorefresh import st_autorefresh
    st_autorefresh(interval=10 * 60 * 1000, key="auto_refresh")
except Exception:
    pass

st.markdown("""
<style>
.stApp { background-color: #0F172A; }
.kpi { background:#1E293B; border:1px solid #334155; border-radius:12px; padding:16px 14px; margin-bottom:12px; }
.kpi-t { font-size:11px; text-transform:uppercase; color:#94A3B8; font-weight:700; letter-spacing:.8px; }
.kpi-v { font-size:26px; font-weight:800; color:#F8FAFC; letter-spacing:-.5px; margin-top:4px; }
.kpi-s { font-size:12px; color:#94A3B8; margin-top:2px; }
.alerta { border-radius:10px; padding:12px 14px; margin-bottom:10px; background:#1E293B; border-left:5px solid; }
.alerta .n { font-size:24px; font-weight:800; color:#F8FAFC; }
.alerta .l { font-size:12px; color:#CBD5E1; font-weight:600; }
.ficha { background:#1E293B; border:1px solid #334155; border-radius:12px; padding:16px; }
.ficha img { width:100%; max-height:230px; object-fit:contain; background:#fff; border-radius:8px; }
.tag { display:inline-block; padding:2px 8px; border-radius:6px; font-size:11px; font-weight:700; margin:2px 4px 2px 0; background:#334155; color:#E2E8F0; }
@media (max-width:768px){ .kpi-v{font-size:20px} .block-container{padding-left:.8rem!important;padding-right:.8rem!important} }
</style>
""", unsafe_allow_html=True)

COLOR_ALERTA = {"quiebre": "#EF4444", "critico": "#F97316", "reponer": "#EAB308", "curva_rota": "#A855F7",
                "acelerando": "#22C55E", "sobrestock": "#38BDF8", "sin_movimiento": "#64748B", "stock_negativo": "#F43F5E"}
TITULO_ALERTA = {"quiebre": "🔴 En quiebre (con demanda)", "critico": "🟠 Críticos: se quiebran antes del lead time",
                 "reponer": "🟡 Bajo punto de pedido", "curva_rota": "🧩 Curva de talles rota",
                 "acelerando": "🚀 Acelerando ventas", "sobrestock": "🧊 Sobrestock",
                 "sin_movimiento": "💤 Sin movimiento 60d", "stock_negativo": "⚠️ Stock negativo"}


def money(x):
    return "$" + f"{x:,.0f}".replace(",", ".") if pd.notna(x) else "-"


def num(x, d=0):
    return f"{x:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".") if pd.notna(x) else "-"


def kpi(col, titulo, valor, sub="", color="#38BDF8"):
    col.markdown(f'<div class="kpi" style="border-top:3px solid {color}"><div class="kpi-t">{titulo}</div>'
                 f'<div class="kpi-v">{valor}</div><div class="kpi-s">{sub}</div></div>', unsafe_allow_html=True)


# ==============================================================================
# DATOS
# ==============================================================================
def _secret(k, default=None):
    try:
        return st.secrets.get(k, os.environ.get(k, default))
    except Exception:
        return os.environ.get(k, default)


@st.cache_data(ttl=600, show_spinner="Cargando datos de Shopify…")
def cargar(_bust=0):
    local = _secret("DATA_DIR_LOCAL")
    if local and os.path.exists(local):
        leer = lambda f: open(os.path.join(local, f), "rb").read()
    else:
        repo = _secret("DATA_REPO", "lucasrulo/reposicion-distrinando")
        rama = _secret("DATA_BRANCH", "data")
        token = _secret("GITHUB_TOKEN")

        def leer(f):
            if token:  # repo privado
                r = requests.get(f"https://api.github.com/repos/{repo}/contents/{f}?ref={rama}", timeout=60,
                                 headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.raw"})
            else:
                r = requests.get(f"https://raw.githubusercontent.com/{repo}/{rama}/{f}", timeout=60)
            r.raise_for_status()
            return r.content

    ventas = pd.read_parquet(io.BytesIO(leer("ventas_diarias.parquet")))
    stock = pd.read_parquet(io.BytesIO(leer("stock_actual.parquet")))
    try:
        hist = pd.read_parquet(io.BytesIO(leer("stock_historial.parquet")))
    except Exception:
        hist = pd.DataFrame(columns=["tienda", "marca", "sku", "disponible", "fecha"])
    try:
        meta = json.loads(leer("meta.json"))
    except Exception:
        meta = {}
    return ventas, stock, hist, meta


@st.cache_data(ttl=600, show_spinner="Calculando reposición…")
def calcular(ventas, stock, hist, ubicaciones, estados, params_json, hoy):
    params = json.loads(params_json)
    params["pesos"] = {int(k): v for k, v in params["pesos"].items()}
    v, s, h = core.preparar(ventas, stock, hist, ubicaciones=list(ubicaciones) or None, incluir_estados=list(estados))
    d = core.calcular_sku(v, s, h, params, hoy)
    m = core.calcular_modelo(d, params)
    return v, h, d, m


# ==============================================================================
# LOGIN (usuarios y hashes en st.secrets -> [usuarios], nunca en el código)
# ==============================================================================
def _hash(p: str) -> str:
    return hashlib.sha256(p.encode("utf-8")).hexdigest()


def login():
    if st.session_state.get("usuario"):
        return
    try:
        usuarios = {k.lower(): v for k, v in dict(st.secrets.get("usuarios", {})).items()}
    except Exception:
        usuarios = {}
    if not usuarios:
        st.error("Falta configurar la sección [usuarios] en los Secrets de Streamlit.")
        st.stop()
    _, c, _ = st.columns([1, 1.2, 1])
    with c:
        st.markdown("<div style='height:8vh'></div>", unsafe_allow_html=True)
        st.markdown("## 📦 Centro de Reposición")
        st.caption("Distrinando · acceso restringido")
        with st.form("login"):
            u = st.text_input("Usuario").strip().lower()
            p = st.text_input("Contraseña", type="password")
            ok = st.form_submit_button("Ingresar", type="primary", width="stretch")
        if ok:
            h = usuarios.get(u)
            if h and hmac.compare_digest(str(h), _hash(p)):
                st.session_state["usuario"] = u
                st.rerun()
            st.error("Usuario o contraseña incorrectos")
    st.stop()


login()
st.sidebar.markdown(f"👤 **{st.session_state['usuario']}**")
if st.sidebar.button("Cerrar sesión", width="stretch"):
    st.session_state.pop("usuario", None)
    st.rerun()

if st.sidebar.button("🔄 Refrescar datos ahora", width="stretch"):
    st.cache_data.clear()

try:
    ventas_raw, stock_raw, hist_raw, meta = cargar()
except Exception as e:
    if "404" in str(e):
        st.info("⏳ **Todavía no hay datos.** El workflow de GitHub Actions no publicó la rama `data` "
                "(no corrió todavía o falló).\n\n"
                "Revisalo en **GitHub → Actions → Sync stock y ventas**. Cuando termine en verde, "
                "tocá **🔄 Refrescar datos ahora**.")
        st.caption(f"Detalle técnico: {e}")
    else:
        st.error(f"No se pudieron cargar los datos: {e}")
    st.stop()

# ==============================================================================
# SIDEBAR / PARÁMETROS
# ==============================================================================
sb = st.sidebar
sb.title("📦 Reposición")
marcas_all = sorted(stock_raw["marca"].dropna().unique())
marcas = sb.multiselect("Marcas", marcas_all, default=marcas_all)
ubic_all = sorted(stock_raw["ubicacion"].dropna().unique())
ubicaciones = sb.multiselect("Ubicaciones que cuentan como stock", ubic_all, default=ubic_all,
                             help="Ej.: sacá ubicaciones de tránsito o de devoluciones")
estados = sb.multiselect("Estado del producto", ["ACTIVE", "UNLISTED", "DRAFT", "ARCHIVED"], default=["ACTIVE", "UNLISTED"])

sb.markdown("### Parámetros de reposición")
c1, c2 = sb.columns(2)
lead_time = c1.number_input("Lead time (días)", 1, 365, core.PARAMS_DEFAULT["lead_time"])
cobertura = c2.number_input("Cobertura (días)", 7, 365, core.PARAMS_DEFAULT["cobertura"])
with sb.expander("Nivel de servicio (stock de seguridad)"):
    sA = st.slider("Clase A", 0.50, 0.99, 0.95, 0.01)
    sB = st.slider("Clase B", 0.50, 0.99, 0.90, 0.01)
    sC = st.slider("Clase C", 0.50, 0.99, 0.80, 0.01)
with sb.expander("Lead time / cobertura por marca"):
    st.caption("Dejá vacío para usar el general.")
    base_ov = pd.DataFrame({"marca": marcas_all, "lead_time": [None] * len(marcas_all), "cobertura": [None] * len(marcas_all)})
    ov = st.data_editor(base_ov, hide_index=True, disabled=["marca"], key="ov",
                        column_config={"lead_time": st.column_config.NumberColumn("LT", min_value=1),
                                       "cobertura": st.column_config.NumberColumn("Cob.", min_value=7)})
with sb.expander("Umbrales de alertas"):
    dias_sobre = st.number_input("Sobrestock si cobertura > (días)", 30, 720, 180)
    acel = st.number_input("Acelerando si v7/v30 ≥", 1.1, 5.0, 1.5, 0.1)
    curva = st.slider("Curva rota si % talles con demanda sin stock ≥", 0.1, 1.0, 0.30, 0.05)
multiplo = sb.number_input("Redondear pedido a múltiplos de", 1, 100, 1, help="Ej.: 6 si el proveedor despacha por caja de 6")

por_marca = {}
for _, r in ov.iterrows():
    o = {}
    if pd.notna(r["lead_time"]): o["lead_time"] = int(r["lead_time"])
    if pd.notna(r["cobertura"]): o["cobertura"] = int(r["cobertura"])
    if o: por_marca[r["marca"]] = o
params = {**core.PARAMS_DEFAULT, "lead_time": int(lead_time), "cobertura": int(cobertura),
          "servicio": {"A": sA, "B": sB, "C": sC}, "dias_sobrestock": int(dias_sobre), "acelera_ratio": float(acel),
          "curva_rota_pct": float(curva), "por_marca": por_marca}

hoy = datetime.now(ZONA_AR).date()
ventas, hist, sku_all, mod_all = calcular(ventas_raw, stock_raw, hist_raw, tuple(ubicaciones), tuple(estados),
                                          json.dumps(params, default=str), hoy)
sku = sku_all[sku_all["marca"].isin(marcas)].copy()
mod = mod_all[mod_all["marca"].isin(marcas)].copy()
if multiplo > 1:
    sku["sugerido"] = (np.ceil(sku["sugerido"] / multiplo) * multiplo).astype(int)
alertas = core.resumen_alertas(sku, mod)

# ==============================================================================
# HEADER + KPIs
# ==============================================================================
act = meta.get("actualizado", "")
try:
    act_dt = datetime.fromisoformat(act).astimezone(ZONA_AR)
    hace = (datetime.now(ZONA_AR) - act_dt).total_seconds() / 3600
    act_txt = f"{act_dt:%d/%m %H:%M} ({'hace ' + num(hace, 1) + ' h'})"
except Exception:
    act_txt, hace = "desconocido", 99
st.markdown(f"## 📦 Centro de Reposición <span style='font-size:14px;color:#94A3B8'>· datos al {act_txt}</span>",
            unsafe_allow_html=True)
errores = {k: v for k, v in meta.get("tiendas", {}).items() if v != "ok"}
if errores:
    st.warning("Tiendas con problemas en la última sincronización: " + ", ".join(f"**{k}** ({v})" for k, v in errores.items()))
if hace > 6:
    st.warning("⏰ Los datos tienen más de 6 horas. Revisá el workflow de GitHub Actions.")

k = st.columns(4)
kpi(k[0], "Venta neta 30d", money(sku["vta30"].sum()), f"{num(sku['u30'].sum())} uds · hoy {num(sku['u_hoy'].sum())} uds")
kpi(k[1], "Velocidad", f"{num(sku['velocidad'].sum(), 1)} uds/día",
    f"cobertura global {num(sku['disponible'].clip(lower=0).sum() / max(sku['velocidad'].sum(), 0.01))} días")
kpi(k[2], "Stock disponible", f"{num(sku['disponible'].clip(lower=0).sum())} uds",
    f"{money(sku['valor_stock'].sum())} · entrante {num(sku['entrante'].sum())}")
kpi(k[3], "Venta perdida estimada", money(sku["venta_perdida_dia"].sum()) + "/día",
    f"{len(alertas['quiebre'])} SKUs en quiebre", "#EF4444")
k = st.columns(4)
kpi(k[0], "SKUs a reponer", num(len(alertas["reponer"])), f"{num(sku['sugerido'].sum())} uds sugeridas", "#EAB308")
kpi(k[1], "Inversión sugerida", money(sku["valor_sugerido"].sum()), "a costo (o precio si no hay costo)", "#EAB308")
kpi(k[2], "Modelos con curva rota", num(len(alertas["curva_rota"])), "faltan talles con demanda", "#A855F7")
kpi(k[3], "Sobrestock + sin movimiento", money(alertas["sobrestock"]["valor_stock"].sum() + alertas["sin_movimiento"]["valor_stock"].sum()),
    f"{len(alertas['sobrestock']) + len(alertas['sin_movimiento'])} SKUs", "#38BDF8")

# ==============================================================================
# COLUMNAS COMUNES
# ==============================================================================
CFG = {
    "img_url": st.column_config.ImageColumn("", width="small"),
    "url_admin": st.column_config.LinkColumn("Admin", display_text="abrir", width="small"),
    "velocidad": st.column_config.NumberColumn("Vel/día", format="%.2f"),
    "cobertura_dias": st.column_config.NumberColumn("Cobertura (d)", format="%.0f"),
    "tendencia": st.column_config.NumberColumn("v7/v30", format="%.2f"),
    "sell_through_30": st.column_config.ProgressColumn("Sell-through 30d", format="percent", min_value=0, max_value=1),
    "curva_pct": st.column_config.ProgressColumn("Curva", format="percent", min_value=0, max_value=1),
    "vta30": st.column_config.NumberColumn("Venta 30d", format="dollar"),
    "vta90": st.column_config.NumberColumn("Venta 90d", format="dollar"),
    "valor_stock": st.column_config.NumberColumn("Valor stock", format="dollar"),
    "valor_sugerido": st.column_config.NumberColumn("Valor sugerido", format="dollar"),
    "venta_perdida_dia": st.column_config.NumberColumn("Venta perdida/día", format="dollar"),
    "precio": st.column_config.NumberColumn("Precio", format="dollar"),
    "fecha_quiebre": st.column_config.DateColumn("Quiebre est.", format="DD/MM/YY"),
    "ultima_venta": st.column_config.DateColumn("Últ. venta", format="DD/MM/YY"),
    "punto_pedido": st.column_config.NumberColumn("Pto. pedido", format="%.0f"),
    "stock_objetivo": st.column_config.NumberColumn("Stock obj.", format="%.0f"),
    "stock_seguridad": st.column_config.NumberColumn("Stock seg.", format="%.0f"),
    "estado_rep": "Estado", "modelo_color": "Modelo+Color", "u_hoy": "Hoy", "u7": "7d", "u14": "14d", "u30": "30d",
    "u60": "60d", "u90": "90d", "disponible": "Disp.", "entrante": "Entrante", "sugerido": "Sugerido", "abc": "ABC",
    "talles": "Talles", "talles_con_stock": "Con stock", "skus_quiebre": "SKUs quebrados", "curva_rota": "Curva rota",
    "acelerando": "🚀", "dias_sin_venta": "Días sin venta",
}
COLS_MOD = ["img_url", "marca", "modelo_color", "producto", "color", "estado_rep", "abc", "u_hoy", "u7", "u30", "u90",
            "velocidad", "tendencia", "disponible", "entrante", "cobertura_dias", "curva_pct", "talles_con_stock", "talles",
            "skus_quiebre", "sugerido", "vta30", "sell_through_30", "venta_perdida_dia", "url_admin"]
COLS_SKU = ["img_url", "marca", "sku", "producto", "color", "talle", "estado_rep", "abc", "u_hoy", "u7", "u30", "u90",
            "velocidad", "tendencia", "disponible", "entrante", "cobertura_dias", "fecha_quiebre", "punto_pedido",
            "stock_objetivo", "sugerido", "valor_sugerido", "sell_through_30", "venta_perdida_dia", "ultima_venta", "url_admin"]


def tabla(df, cols, key=None, select=False, height=None):
    cols = [c for c in cols if c in df.columns]
    kw = dict(hide_index=True, width="stretch", column_config=CFG, height=height or "auto")
    if select:
        return st.dataframe(df[cols], key=key, on_select="rerun", selection_mode="single-row", **kw)
    st.dataframe(df[cols], key=key, **kw)


def a_excel(hojas: dict) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        for nombre, df in hojas.items():
            df.to_excel(xw, sheet_name=str(nombre)[:31], index=False)
    return buf.getvalue()


def detalle_modelo(fila):
    """Ficha Modelo+Color con desglose SKU por talle."""
    d = sku[(sku["tienda"] == fila["tienda"]) & (sku["modelo_color"] == fila["modelo_color"])].copy()
    d = d.iloc[sorted(range(len(d)), key=lambda i: core.clave_talle(d.iloc[i]["talle"]))]
    c1, c2 = st.columns([1, 3])
    with c1:
        img = fila.get("img_url") or ""
        st.markdown(f'<div class="ficha">{f"<img src={img!r}>" if img else ""}'
                    f'<h4 style="margin:10px 0 4px">{fila["producto"]}</h4>'
                    f'<div style="color:#94A3B8;font-size:13px">{fila["modelo_color"]} · {fila["color"]} · {fila["marca"]}</div>'
                    f'<div style="margin-top:8px"><span class="tag">{fila["estado_rep"]}</span><span class="tag">ABC {fila["abc"]}</span>'
                    f'{"<span class=tag>🧩 Curva rota</span>" if fila["curva_rota"] else ""}'
                    f'{"<span class=tag>🚀 Acelerando</span>" if fila["acelerando"] else ""}</div>'
                    f'<p style="margin-top:10px;font-size:13px;color:#CBD5E1">Vel: <b>{num(fila["velocidad"], 2)}</b> uds/día<br>'
                    f'Disp: <b>{num(fila["disponible"])}</b> · Entrante: <b>{num(fila["entrante"])}</b><br>'
                    f'Cobertura: <b>{num(fila["cobertura_dias"]) if np.isfinite(fila["cobertura_dias"]) else "∞"}</b> días<br>'
                    f'Reponer: <b>{num(d["sugerido"].sum())}</b> uds ({money(d["valor_sugerido"].sum())})</p>'
                    f'<a href="{fila["url_admin"]}" target="_blank">Abrir en Shopify ↗</a></div>', unsafe_allow_html=True)
    with c2:
        fig = go.Figure()
        fig.add_bar(x=d["talle"].astype(str), y=d["disponible"].clip(lower=0), name="Disponible", marker_color="#38BDF8")
        fig.add_bar(x=d["talle"].astype(str), y=d["entrante"], name="Entrante", marker_color="#818CF8")
        fig.add_bar(x=d["talle"].astype(str), y=d["u30"], name="Vendido 30d", marker_color="#22C55E")
        fig.add_bar(x=d["talle"].astype(str), y=d["sugerido"], name="Sugerido", marker_color="#EAB308")
        fig.update_layout(barmode="group", height=280, title="Curva de talles", template="plotly_dark",
                          paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", margin=dict(l=10, r=10, t=40, b=10),
                          legend=dict(orientation="h", y=-0.2), xaxis_type="category")
        st.plotly_chart(fig, width="stretch")

        skus = set(d["sku"])
        vv = ventas[(ventas["tienda"] == fila["tienda"]) & ventas["sku"].isin(skus)]
        serie = vv.groupby("fecha")["unidades"].sum().reindex(
            pd.date_range(pd.Timestamp(hoy) - pd.Timedelta(days=90), pd.Timestamp(hoy)), fill_value=0)
        fig2 = go.Figure()
        fig2.add_bar(x=serie.index, y=serie.values, name="Unidades/día", marker_color="#22C55E", opacity=.6)
        fig2.add_scatter(x=serie.index, y=serie.rolling(7, min_periods=1).mean(), name="Media 7d", line=dict(color="#F8FAFC"))
        if not hist.empty:
            hh = hist[(hist["tienda"] == fila["tienda"]) & hist["sku"].isin(skus)].groupby("fecha")["disponible"].sum()
            if not hh.empty:
                fig2.add_scatter(x=hh.index, y=hh.values, name="Stock", yaxis="y2", line=dict(color="#38BDF8", dash="dot"))
        fig2.update_layout(height=260, title="Ventas diarias (90d) vs stock", template="plotly_dark",
                           paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", margin=dict(l=10, r=10, t=40, b=10),
                           yaxis2=dict(overlaying="y", side="right", showgrid=False), legend=dict(orientation="h", y=-0.25))
        st.plotly_chart(fig2, width="stretch")
    st.markdown("**Desglose por SKU**")
    tabla(d, [c for c in COLS_SKU if c not in ("img_url", "marca", "producto", "color", "url_admin")], key=f"det_{fila['modelo_color']}")


# ==============================================================================
# TABS
# ==============================================================================
tab_al, tab_mod, tab_sku, tab_plan, tab_tend = st.tabs(
    ["🚨 Alertas", "👟 Modelo + Color", "🔎 SKU", "📦 Plan de reposición", "📈 Tendencias"])

# ---------------- ALERTAS ----------------
with tab_al:
    claves = list(TITULO_ALERTA)
    cols = st.columns(4)
    for i, k_ in enumerate(claves):
        cols[i % 4].markdown(f'<div class="alerta" style="border-left-color:{COLOR_ALERTA[k_]}">'
                             f'<div class="n">{num(len(alertas[k_]))}</div><div class="l">{TITULO_ALERTA[k_]}</div></div>',
                             unsafe_allow_html=True)

    por_marca_estado = sku.groupby(["marca", "estado_rep"]).size().reset_index(name="skus")
    fig = go.Figure()
    colores = {"🔴 Quiebre": "#EF4444", "🟠 Crítico": "#F97316", "🟡 Reponer": "#EAB308", "🧊 Sobrestock": "#38BDF8",
               "💤 Sin movimiento": "#64748B", "🟢 OK": "#22C55E", "⚪ Sin demanda": "#334155"}
    for e in core.ESTADOS:
        x = por_marca_estado[por_marca_estado["estado_rep"] == e]
        fig.add_bar(y=x["marca"], x=x["skus"], name=e, orientation="h", marker_color=colores[e])
    fig.update_layout(barmode="stack", height=60 + 40 * max(len(marcas), 1), template="plotly_dark", title="Salud del surtido por marca (SKUs)",
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", margin=dict(l=10, r=10, t=40, b=10),
                      legend=dict(orientation="h", y=-0.15))
    st.plotly_chart(fig, width="stretch")

    sub = st.tabs([TITULO_ALERTA[k_] + f" ({len(alertas[k_])})" for k_ in claves])
    for t, k_ in zip(sub, claves):
        with t:
            df = alertas[k_]
            if df.empty:
                st.success("Nada por acá 👌")
                continue
            tabla(df, COLS_MOD if k_ in ("curva_rota", "acelerando") else COLS_SKU, key=f"al_{k_}", height=450)
            st.download_button("⬇️ Descargar Excel", a_excel({k_: df.drop(columns=["img_url"], errors="ignore")}),
                               f"alerta_{k_}_{hoy}.xlsx", key=f"dl_{k_}")

# ---------------- MODELO + COLOR ----------------
with tab_mod:
    f1, f2, f3, f4 = st.columns([2, 2, 1, 1])
    q = f1.text_input("Buscar (código, nombre, color)", key="q_mod")
    est_sel = f2.multiselect("Estado", core.ESTADOS, key="est_mod")
    abc_sel = f3.multiselect("ABC", ["A", "B", "C"], key="abc_mod")
    orden = f4.selectbox("Ordenar por", ["Venta 30d", "Velocidad", "Venta perdida", "Sugerido", "Cobertura ↑", "Tendencia"])
    flt = mod.copy()
    if q:
        qq = q.lower()
        flt = flt[flt[["modelo_color", "producto", "color"]].astype(str).apply(lambda c: c.str.lower().str.contains(qq, regex=False)).any(axis=1)]
    if est_sel: flt = flt[flt["estado_rep"].isin(est_sel)]
    if abc_sel: flt = flt[flt["abc"].isin(abc_sel)]
    col_orden = {"Venta 30d": ("vta30", False), "Velocidad": ("velocidad", False), "Venta perdida": ("venta_perdida_dia", False),
                 "Sugerido": ("sugerido", False), "Cobertura ↑": ("cobertura_dias", True), "Tendencia": ("tendencia", False)}[orden]
    flt = flt.sort_values(col_orden[0], ascending=col_orden[1]).reset_index(drop=True)
    st.caption(f"{len(flt)} modelos · seleccioná una fila para ver el desglose por SKU/talle")
    ev = tabla(flt, COLS_MOD, key="tabla_mod", select=True, height=480)
    filas = ev.selection.rows if ev is not None else []
    if filas:
        st.divider()
        detalle_modelo(flt.iloc[filas[0]])

# ---------------- SKU ----------------
with tab_sku:
    f1, f2, f3 = st.columns([2, 2, 1])
    q = f1.text_input("Buscar SKU / nombre", key="q_sku")
    est_sel = f2.multiselect("Estado", core.ESTADOS, key="est_sku")
    solo_dem = f3.checkbox("Solo con ventas 90d", value=True)
    flt = sku.copy()
    if q:
        qq = q.lower()
        flt = flt[flt[["sku", "producto", "color"]].astype(str).apply(lambda c: c.str.lower().str.contains(qq, regex=False)).any(axis=1)]
    if est_sel: flt = flt[flt["estado_rep"].isin(est_sel)]
    if solo_dem: flt = flt[flt["u90"] > 0]
    flt = flt.sort_values("velocidad", ascending=False)
    st.caption(f"{len(flt)} SKUs")
    tabla(flt, COLS_SKU, key="tabla_sku", height=600)
    st.download_button("⬇️ Descargar Excel", a_excel({"sku": flt.drop(columns=["img_url"], errors="ignore")}), f"skus_{hoy}.xlsx")

# ---------------- PLAN DE REPOSICIÓN ----------------
with tab_plan:
    st.markdown("Ajustá cantidades, destildá lo que no quieras pedir y descargá el pedido por marca.")
    p1, p2 = st.columns([2, 1])
    prioridad = p1.multiselect("Incluir estados", core.ESTADOS[:3], default=core.ESTADOS[:3])
    solo_ab = p2.checkbox("Solo clase A y B", value=False)
    plan = sku[(sku["sugerido"] > 0) & sku["estado_rep"].isin(prioridad)].copy()
    if solo_ab:
        plan = plan[plan["abc"].isin(["A", "B"])]
    plan["prio"] = plan["estado_rep"].map(core.PRIORIDAD)
    plan = plan.sort_values(["prio", "abc", "venta_perdida_dia"], ascending=[True, True, False])
    plan.insert(0, "pedir", True)
    plan["a_pedir"] = plan["sugerido"]
    cols_plan = ["pedir", "marca", "sku", "producto", "color", "talle", "estado_rep", "abc", "velocidad", "disponible",
                 "entrante", "cobertura_dias", "fecha_quiebre", "sugerido", "a_pedir", "costo", "precio"]
    edit = st.data_editor(plan[cols_plan], hide_index=True, width="stretch", height=520, key="plan_ed",
                          disabled=[c for c in cols_plan if c not in ("pedir", "a_pedir")],
                          column_config={**CFG, "pedir": st.column_config.CheckboxColumn("✔"),
                                         "a_pedir": st.column_config.NumberColumn("A pedir ✏️", min_value=0, step=1),
                                         "costo": st.column_config.NumberColumn("Costo", format="dollar")})
    final = edit[edit["pedir"] & (edit["a_pedir"] > 0)].copy()
    final["valor"] = final["a_pedir"] * final["costo"].fillna(final["precio"])
    res = final.groupby("marca").agg(skus=("sku", "count"), unidades=("a_pedir", "sum"), valor=("valor", "sum")).reset_index()
    c1, c2, c3 = st.columns(3)
    kpi(c1, "SKUs en el pedido", num(len(final)), color="#EAB308")
    kpi(c2, "Unidades", num(final["a_pedir"].sum()), color="#EAB308")
    kpi(c3, "Valor", money(final["valor"].sum()), color="#EAB308")
    st.dataframe(res, hide_index=True, width="stretch",
                 column_config={"valor": st.column_config.NumberColumn("Valor", format="dollar")})
    hojas = {"Resumen": res}
    for m_, g in final.groupby("marca"):
        hojas[m_] = g[["sku", "producto", "color", "talle", "a_pedir", "disponible", "entrante", "velocidad", "cobertura_dias", "estado_rep"]]
    b1, b2 = st.columns(2)
    b1.download_button("⬇️ Pedido en Excel (una hoja por marca)", a_excel(hojas), f"pedido_reposicion_{hoy}.xlsx",
                       type="primary", width="stretch", disabled=final.empty)
    b2.download_button("⬇️ CSV (SKU;cantidad)", final[["sku", "a_pedir"]].to_csv(index=False, sep=";").encode("utf-8-sig"),
                       f"pedido_reposicion_{hoy}.csv", width="stretch", disabled=final.empty)

# ---------------- TENDENCIAS ----------------
with tab_tend:
    vv = ventas[ventas["marca"].isin(marcas)]
    if not vv.empty:
        sem = vv.assign(semana=vv["fecha"].dt.to_period("W-SUN").dt.start_time).groupby(["semana", "marca"])["unidades"].sum().reset_index()
        sem = sem[sem["semana"] < pd.Timestamp(hoy) - pd.Timedelta(days=pd.Timestamp(hoy).dayofweek)]  # solo semanas cerradas
        fig = go.Figure()
        for m_, g in sem.groupby("marca"):
            fig.add_scatter(x=g["semana"], y=g["unidades"], name=m_, mode="lines+markers")
        fig.update_layout(height=340, title="Unidades por semana (semanas cerradas)", template="plotly_dark",
                          paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", margin=dict(l=10, r=10, t=40, b=10))
        st.plotly_chart(fig, width="stretch")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**🚀 Top 20 que más aceleran (v7 vs v30)**")
        tabla(mod[mod["u7"] >= 3].sort_values("tendencia", ascending=False).head(20),
              ["img_url", "marca", "modelo_color", "producto", "u7", "u30", "tendencia", "disponible", "cobertura_dias", "estado_rep"], key="t_up")
    with c2:
        st.markdown("**📉 Top 20 que más desaceleran**")
        tabla(mod[mod["u30"] >= 10].sort_values("tendencia").head(20),
              ["img_url", "marca", "modelo_color", "producto", "u7", "u30", "tendencia", "disponible", "cobertura_dias", "estado_rep"], key="t_down")
    st.markdown("**🏆 Top 30 modelos por velocidad**")
    tabla(mod.sort_values("velocidad", ascending=False).head(30), COLS_MOD, key="t_top")

st.caption("Velocidad = 0,5·v14 + 0,3·v30 + 0,2·v60 descontando días sin stock · Stock seguridad = z(ABC)·σ·√LT · "
           "Punto de pedido = vel·LT + SS · Objetivo = vel·(LT+cobertura) + SS")
