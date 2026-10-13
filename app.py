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
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap');
:root { --papel:#F3EEE3; --tinta:#0A0A0A; --senal:#FF4F00; --gris:#8C8577; --linea:#0A0A0A; --azul:#2F5BFF; }
html, body, .stApp, [data-testid="stMarkdownContainer"], input, textarea, label, p, li, button p { font-family:'IBM Plex Mono', ui-monospace, monospace !important; }
.stApp { background-color:var(--papel);
  background-image:linear-gradient(rgba(10,10,10,.045) 1px, transparent 1px), linear-gradient(90deg, rgba(10,10,10,.045) 1px, transparent 1px);
  background-size:28px 28px; }
.block-container { padding-top:1.2rem !important; max-width:1500px; }
[data-testid="stHeader"] { height:0; }
* { border-radius:0 !important; }
h1,h2,h3,h4 { font-family:'Space Grotesk', sans-serif !important; letter-spacing:-.03em; color:var(--tinta); }
header[data-testid="stHeader"] { background:transparent; }

/* ---- sidebar invertida ---- */
section[data-testid="stSidebar"] { background:var(--tinta); border-right:3px solid var(--senal); }
section[data-testid="stSidebar"] * { color:var(--papel); }
section[data-testid="stSidebar"] input, section[data-testid="stSidebar"] [data-baseweb="select"] * { color:var(--tinta) !important; }
section[data-testid="stSidebar"] [data-baseweb="tag"] { background:var(--senal) !important; }
section[data-testid="stSidebar"] [data-baseweb="tag"] * { color:var(--tinta) !important; }
section[data-testid="stSidebar"] h1, section[data-testid="stSidebar"] h2, section[data-testid="stSidebar"] h3 { color:var(--papel); text-transform:uppercase; }
section[data-testid="stSidebar"] button { background:transparent; border:2px solid var(--papel); }
section[data-testid="stSidebar"] button:hover { background:var(--senal); border-color:var(--senal); }
section[data-testid="stSidebar"] button:hover * { color:var(--tinta); }

/* ---- masthead ---- */
.mast { border-top:6px solid var(--tinta); border-bottom:2px solid var(--tinta); margin-bottom:0; }
.mast-top { display:flex; justify-content:space-between; font-size:11px; letter-spacing:.14em; text-transform:uppercase; padding:6px 0; border-bottom:1px solid var(--tinta); }
.mast-title { font-family:'Space Grotesk',sans-serif; font-weight:700; font-size:clamp(54px, 9.5vw, 150px); line-height:.82; letter-spacing:-.065em; color:var(--tinta); padding:34px 0 12px; }
.mast-title .dot { color:var(--senal); }
.mast-sub { display:flex; gap:28px; font-size:12px; text-transform:uppercase; letter-spacing:.08em; padding:6px 0 8px; }
.mast-sub b { background:var(--tinta); color:var(--papel); padding:0 6px; }
.ticker { overflow:hidden; white-space:nowrap; background:var(--senal); color:var(--tinta); border-bottom:2px solid var(--tinta);
  font-weight:600; font-size:13px; letter-spacing:.06em; text-transform:uppercase; padding:9px 0; margin-bottom:22px; }
.ticker-in { display:inline-block; padding-left:100%; animation:tick 55s linear infinite; }
@keyframes tick { from { transform:translateX(0) } to { transform:translateX(-100%) } }

/* ---- grilla de KPIs ---- */
.grid { display:grid; grid-template-columns:repeat(4, 1fr); border-top:2px solid var(--linea); border-left:2px solid var(--linea); margin-bottom:18px; background:var(--papel); }
.cell { border-right:2px solid var(--linea); border-bottom:2px solid var(--linea); padding:14px 16px 16px; position:relative; min-height:128px; }
.cell .ix { position:absolute; top:10px; right:12px; font-size:10px; color:var(--gris); }
.cell .t { font-size:11px; text-transform:uppercase; letter-spacing:.12em; font-weight:600; }
.cell .v { font-family:'Space Grotesk',sans-serif; font-weight:700; font-size:clamp(28px, 3.1vw, 46px); letter-spacing:-.04em; line-height:1; margin:14px 0 8px; color:var(--tinta); }
.cell .s { font-size:11.5px; color:#3b3833; }
.cell.hot { background:var(--senal); }
.cell.hot .ix, .cell.hot .s { color:var(--tinta); }
.cell.ink { background:var(--tinta); }
.cell.ink .t, .cell.ink .s, .cell.ink .ix { color:var(--papel); }
.cell.ink .v { color:var(--senal); }
.cell .sq { display:inline-block; width:10px; height:10px; margin-right:7px; border:1.5px solid var(--tinta); vertical-align:-1px; }

/* ---- tabs ---- */
[role="tablist"] { gap:0 !important; border-bottom:2px solid var(--tinta) !important; }
[role="tab"] { border:2px solid var(--tinta) !important; border-bottom:none !important; margin:0 -2px 0 0 !important; padding:10px 18px !important; background:var(--papel) !important; height:auto !important; }
[role="tab"] p { font-size:12px !important; text-transform:uppercase; letter-spacing:.1em; font-weight:600; color:var(--tinta) !important; }
[role="tab"][aria-selected="true"] { background:var(--tinta) !important; }
[role="tab"][aria-selected="true"] p { color:var(--senal) !important; }
[role="tab"]:hover p { color:var(--senal) !important; }
[data-baseweb="tab-highlight"], [data-baseweb="tab-border"] { display:none !important; }

/* ---- tablas, botones, inputs ---- */
[data-testid="stDataFrame"], [data-testid="stDataEditor"] { border:2px solid var(--tinta); background:#fff; }
.stButton button, .stDownloadButton button, .stFormSubmitButton button { border:2px solid var(--tinta) !important; font-weight:600; text-transform:uppercase; letter-spacing:.08em; box-shadow:4px 4px 0 var(--tinta); transition:all .08s; }
.stButton button:active, .stDownloadButton button:active { box-shadow:0 0 0 var(--tinta); transform:translate(4px,4px); }
[data-baseweb="input"], [data-baseweb="select"] > div { border:2px solid var(--tinta) !important; background:#fff !important; }
.sec { font-family:'Space Grotesk',sans-serif; font-weight:700; font-size:22px; letter-spacing:-.03em; border-bottom:2px solid var(--tinta); padding-bottom:4px; margin:18px 0 10px; text-transform:uppercase; }
.sec small { font-family:'IBM Plex Mono',monospace; font-size:11px; font-weight:500; letter-spacing:.1em; color:var(--gris); margin-left:10px; }

/* ---- ficha de producto ---- */
.ficha { background:#fff; border:2px solid var(--tinta); box-shadow:8px 8px 0 var(--tinta); }
.ficha img { width:100%; max-height:240px; object-fit:contain; background:#fff; border-bottom:2px solid var(--tinta); display:block; }
.ficha .in { padding:14px; }
.ficha h4 { font-size:22px; margin:0 0 4px; line-height:1.05; }
.ficha .meta { font-size:11px; text-transform:uppercase; letter-spacing:.08em; color:var(--gris); }
.ficha .row { display:flex; justify-content:space-between; border-top:1px solid var(--tinta); padding:6px 0; font-size:12.5px; }
.ficha .row b { font-family:'Space Grotesk',sans-serif; font-size:16px; }
.ficha a { display:block; text-align:center; background:var(--tinta); color:var(--papel) !important; padding:10px; text-decoration:none; text-transform:uppercase; letter-spacing:.1em; font-size:12px; margin-top:8px; }
.ficha a:hover { background:var(--senal); color:var(--tinta) !important; }
.tag { display:inline-block; padding:2px 7px; font-size:10.5px; font-weight:600; margin:6px 5px 0 0; background:var(--tinta); color:var(--papel); text-transform:uppercase; letter-spacing:.06em; }
.tag.hot { background:var(--senal); color:var(--tinta); }

/* ---- vitrina ---- */
.card { background:#fff; border:2px solid var(--tinta); margin-bottom:6px; position:relative; transition:transform .1s, box-shadow .1s; }
.card:hover { transform:translate(-3px,-3px); box-shadow:6px 6px 0 var(--tinta); }
.card .ph { height:190px; display:flex; align-items:center; justify-content:center; border-bottom:2px solid var(--tinta); background:#fff; overflow:hidden; }
.card .ph img { max-width:100%; max-height:186px; object-fit:contain; }
.card .badge { position:absolute; top:0; left:0; padding:3px 8px; font-size:10px; font-weight:600; text-transform:uppercase; letter-spacing:.08em; border-right:2px solid var(--tinta); border-bottom:2px solid var(--tinta); }
.card .abc { position:absolute; top:0; right:0; padding:3px 8px; font-size:10px; font-weight:600; background:var(--tinta); color:var(--papel); }
.card .bd { padding:10px 10px 8px; }
.card .nm { font-family:'Space Grotesk',sans-serif; font-weight:700; font-size:15px; line-height:1.1; height:34px; overflow:hidden; letter-spacing:-.02em; }
.card .cd { font-size:10px; color:var(--gris); text-transform:uppercase; letter-spacing:.06em; margin:3px 0 8px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.card .tl { display:flex; flex-wrap:wrap; gap:3px; margin-bottom:8px; }
.card .tl span { font-size:10px; min-width:24px; text-align:center; padding:2px 3px; border:1.5px solid var(--tinta); font-weight:600; }
.card .tl .on { background:var(--tinta); color:var(--papel); }
.card .tl .br { background:var(--senal); border-color:var(--senal); color:var(--tinta); }
.card .tl .off { color:#B8B0A0; border-color:#D8D0BF; }
.card .st { display:grid; grid-template-columns:repeat(3,1fr); border-top:1.5px solid var(--tinta); }
.card .st div { padding:6px 0 2px; font-size:9.5px; text-transform:uppercase; letter-spacing:.06em; color:var(--gris); }
.card .st div + div { border-left:1.5px solid var(--tinta); padding-left:7px; }
.card .st b { display:block; font-family:'Space Grotesk',sans-serif; font-size:17px; color:var(--tinta); letter-spacing:-.02em; }
.card .rp { background:var(--senal); font-size:11px; font-weight:600; text-transform:uppercase; letter-spacing:.08em; padding:6px 10px; display:flex; justify-content:space-between; border-top:2px solid var(--tinta); }
.card .rp.no { background:var(--papel); color:var(--gris); }
.legend-tl { font-size:11px; margin:-4px 0 12px; }
.legend-tl span { display:inline-block; width:14px; height:12px; border:1.5px solid var(--tinta); vertical-align:-2px; margin:0 5px 0 14px; }
.login-t { font-family:'Space Grotesk',sans-serif; font-weight:700; font-size:clamp(48px,7vw,96px); letter-spacing:-.06em; line-height:.85; }
.login-t span { color:var(--senal); }
@media (max-width:900px){ .grid{grid-template-columns:repeat(2,1fr)} .mast-sub{flex-wrap:wrap; gap:8px 18px} }
</style>
""", unsafe_allow_html=True)

TINTA, PAPEL, SENAL, GRIS, AZUL = "#0A0A0A", "#F3EEE3", "#FF4F00", "#8C8577", "#2F5BFF"
COLOR_ALERTA = {"quiebre": SENAL, "critico": "#FF9E00", "reponer": "#FFD000", "curva_rota": "#B04CFF",
                "acelerando": "#00A676", "sobrestock": AZUL, "sin_movimiento": GRIS, "stock_negativo": TINTA}
COLOR_ESTADO = {"🔴 Quiebre": SENAL, "🟠 Crítico": "#FF9E00", "🟡 Reponer": "#FFD000", "🧊 Sobrestock": AZUL,
                "💤 Sin movimiento": GRIS, "🟢 OK": TINTA, "⚪ Sin demanda": "#D8D0BF"}
COLOR_MARCAS = [TINTA, SENAL, AZUL, "#E0B400", GRIS, "#00A676", "#B04CFF", "#D8D0BF"]
LABEL_ALERTA = {"quiebre": "Quiebre con demanda", "critico": "Se quiebran antes del lead time",
                "reponer": "Bajo punto de pedido", "curva_rota": "Curva de talles rota",
                "acelerando": "Acelerando", "sobrestock": "Sobrestock",
                "sin_movimiento": "Sin movimiento 60d", "stock_negativo": "Stock negativo"}
TITULO_ALERTA = {"quiebre": "🔴 En quiebre (con demanda)", "critico": "🟠 Críticos: se quiebran antes del lead time",
                 "reponer": "🟡 Bajo punto de pedido", "curva_rota": "🧩 Curva de talles rota",
                 "acelerando": "🚀 Acelerando ventas", "sobrestock": "🧊 Sobrestock",
                 "sin_movimiento": "💤 Sin movimiento 60d", "stock_negativo": "⚠️ Stock negativo"}


def money(x):
    return "$" + f"{x:,.0f}".replace(",", ".") if pd.notna(x) else "-"


def num(x, d=0):
    return f"{x:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".") if pd.notna(x) else "-"


def grilla(items, cols=4, destino=st):
    """items: (titulo, valor, sub, clase) — clase '' | 'hot' | 'ink'"""
    html = "".join(f'<div class="cell {c}"><span class="ix">{i + 1:02d}</span><div class="t">{t}</div>'
                   f'<div class="v">{v}</div><div class="s">{s_}</div></div>' for i, (t, v, s_, c) in enumerate(items))
    destino.markdown(f'<div class="grid" style="grid-template-columns:repeat({cols},1fr)">{html}</div>', unsafe_allow_html=True)


def seccion(titulo, nota="", destino=st):
    destino.markdown(f'<div class="sec">{titulo}<small>{nota}</small></div>', unsafe_allow_html=True)


def estilo(fig, titulo="", h=300, **kw):
    fig.update_layout(
        height=h, template="plotly_white", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="IBM Plex Mono, monospace", size=11, color=TINTA),
        title=dict(text=titulo.upper(), font=dict(family="Space Grotesk, sans-serif", size=15, color=TINTA), x=0, xanchor="left"),
        margin=dict(l=8, r=8, t=44 if titulo else 10, b=8), bargap=0.18,
        legend=dict(orientation="h", y=-0.18, x=0, font=dict(size=10.5)), hoverlabel=dict(bgcolor=TINTA, font_color=PAPEL),
        **kw)
    fig.update_xaxes(showline=True, linewidth=2, linecolor=TINTA, gridcolor="rgba(10,10,10,.08)", ticks="outside", tickcolor=TINTA)
    fig.update_yaxes(showline=True, linewidth=2, linecolor=TINTA, gridcolor="rgba(10,10,10,.08)", zeroline=False)
    return fig


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
        st.markdown('<div class="mast-top" style="border-top:6px solid #0A0A0A">'
                    '<span>Distrinando / E-commerce</span><span>Acceso restringido</span></div>'
                    '<div class="login-t">REPOSI<br>CIÓN<span>.</span></div><br>', unsafe_allow_html=True)
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
st.sidebar.markdown(f"<div style='font-size:11px;letter-spacing:.14em;text-transform:uppercase'>Sesión ▸ "
                    f"<b style='color:#FF4F00'>{st.session_state['usuario']}</b></div>", unsafe_allow_html=True)
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
sb.markdown("### Parámetros")
marcas_all = sorted(stock_raw["marca"].dropna().unique())
marcas = sb.multiselect("Marcas", marcas_all, default=marcas_all)
ubic_all = sorted(stock_raw["ubicacion"].dropna().unique())
ubicaciones = (sb.multiselect("Ubicaciones que cuentan como stock", ubic_all, default=ubic_all)
               if len(ubic_all) > 1 else ubic_all)
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
multiplo = sb.number_input("Redondear pedido a múltiplos de", 1, 100, 1)

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
RE_TEMP = r"((?:SS|FW|AW|OI|PV|SP|FA|HO)\d{2})$"
AZURE = "https://distriecomm.blob.core.windows.net/catalogo"


def enriquecer(df):
    df = df.copy()
    df["temporada"] = df["modelo_color"].astype(str).str.upper().str.extract(RE_TEMP, expand=False).fillna("S/T")
    vacia = df["img_url"].fillna("").eq("")
    df.loc[vacia, "img_url"] = AZURE + "/" + df.loc[vacia, "marca"].astype(str) + "/" + df.loc[vacia, "modelo_color"].astype(str).str.upper() + "-1.jpg"
    return df


sku_all, mod_all = enriquecer(sku_all), enriquecer(mod_all)
temps_all = sorted(t for t in mod_all["temporada"].unique() if t != "S/T") + (["S/T"] if (mod_all["temporada"] == "S/T").any() else [])
temporadas = sb.multiselect("Temporada", temps_all, default=temps_all) if len(temps_all) > 1 else temps_all
sku = sku_all[sku_all["marca"].isin(marcas) & sku_all["temporada"].isin(temporadas)].copy()
mod = mod_all[mod_all["marca"].isin(marcas) & mod_all["temporada"].isin(temporadas)].copy()
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
vp = sku["venta_perdida_dia"].sum()
tick = (f"▲ {num(len(alertas['quiebre']))} SKUs en quiebre ✱ {money(vp)} por día de venta perdida ✱ "
        f"{num(len(alertas['critico']))} se quiebran antes del lead time ✱ {num(sku['sugerido'].sum())} uds sugeridas para reponer ✱ "
        f"{num(len(alertas['curva_rota']))} modelos con curva rota ✱ {num(len(alertas['acelerando']))} modelos acelerando ✱ ")
st.markdown(f"""
<div class="mast">
  <div class="mast-top"><span>Distrinando / E-commerce / Centro de comando</span><span>Datos al {act_txt}</span></div>
  <div class="mast-title">REPOSICIÓN<span class="dot">.</span></div>
  <div class="mast-sub"><span>Marcas <b>{len(marcas)}</b></span><span>SKUs <b>{num(len(sku))}</b></span>
    <span>Modelos <b>{num(len(mod))}</b></span><span>Lead time <b>{int(lead_time)}d</b></span><span>Cobertura <b>{int(cobertura)}d</b></span></div>
</div>
<div class="ticker"><div class="ticker-in">{tick * 3}</div></div>
""", unsafe_allow_html=True)
errores = {k: v for k, v in meta.get("tiendas", {}).items() if v != "ok"}
if errores:
    st.warning("Tiendas con problemas en la última sincronización: " + ", ".join(f"**{k}** ({v})" for k, v in errores.items()))
if hace > 6:
    st.warning("⏰ Los datos tienen más de 6 horas. Revisá el workflow de GitHub Actions.")

disp_tot = sku["disponible"].clip(lower=0).sum()
grilla([
    ("Velocidad", f"{num(sku['velocidad'].sum(), 1)}<small style='font-size:.4em'> uds/día</small>",
     f"cobertura global {num(disp_tot / max(sku['velocidad'].sum(), 0.01))} días", ""),
    ("Stock disponible", num(disp_tot), f"{money(sku['valor_stock'].sum())} · entrante {num(sku['entrante'].sum())}", ""),
    ("Venta perdida / día", money(vp), f"{len(alertas['quiebre'])} SKUs en quiebre con demanda", "hot"),
    ("SKUs a reponer", num(len(alertas["reponer"])), f"{num(sku['sugerido'].sum())} uds sugeridas", "ink"),
    ("Curva rota", num(len(alertas["curva_rota"])), "modelos sin talles con demanda", ""),
    ("Capital inmovilizado", money(alertas["sobrestock"]["valor_stock"].sum() + alertas["sin_movimiento"]["valor_stock"].sum()),
     f"{len(alertas['sobrestock']) + len(alertas['sin_movimiento'])} SKUs sobrestock / sin mov.", ""),
], cols=3)

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
    "vta30": st.column_config.NumberColumn("Venta 30d", format="localized"),
    "vta90": st.column_config.NumberColumn("Venta 90d", format="localized"),
    "valor_stock": st.column_config.NumberColumn("Valor stock", format="localized"),
    "valor_sugerido": st.column_config.NumberColumn("Valor sugerido", format="localized"),
    "venta_perdida_dia": st.column_config.NumberColumn("Venta perdida/día", format="localized"),
    "precio": st.column_config.NumberColumn("Precio", format="localized"),
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


def detalle_modelo(fila, pref="m"):
    """Ficha Modelo+Color con desglose SKU por talle."""
    d = sku[(sku["tienda"] == fila["tienda"]) & (sku["modelo_color"] == fila["modelo_color"])].copy()
    d = d.iloc[sorted(range(len(d)), key=lambda i: core.clave_talle(d.iloc[i]["talle"]))]
    c1, c2 = st.columns([1, 3])
    with c1:
        img = fila.get("img_url") or ""
        cob = num(fila["cobertura_dias"]) if np.isfinite(fila["cobertura_dias"]) else "∞"
        tags = (f'<span class="tag {"hot" if fila["estado_rep"] in core.ESTADOS[:2] else ""}">{fila["estado_rep"][2:]}</span>'
                f'<span class="tag">ABC {fila["abc"]}</span>'
                + ('<span class="tag hot">Curva rota</span>' if fila["curva_rota"] else "")
                + ('<span class="tag">▲ Acelerando</span>' if fila["acelerando"] else ""))
        st.markdown(f'<div class="ficha">{f"<img src={img!r}>" if img else ""}<div class="in">'
                    f'<div class="meta">{fila["marca"]} / {fila["modelo_color"]} / {fila["color"]}</div>'
                    f'<h4>{fila["producto"]}</h4>{tags}<div style="height:10px"></div>'
                    f'<div class="row"><span>Velocidad</span><b>{num(fila["velocidad"], 2)}/día</b></div>'
                    f'<div class="row"><span>Disponible</span><b>{num(fila["disponible"])}</b></div>'
                    f'<div class="row"><span>Entrante</span><b>{num(fila["entrante"])}</b></div>'
                    f'<div class="row"><span>Cobertura</span><b>{cob} d</b></div>'
                    f'<div class="row" style="background:#FF4F00;margin:0 -14px;padding:6px 14px"><span>Reponer</span>'
                    f'<b>{num(d["sugerido"].sum())} uds</b></div>'
                    f'<a href="{fila["url_admin"]}" target="_blank">Abrir en Shopify ↗</a></div></div>', unsafe_allow_html=True)
    with c2:
        x = d["talle"].astype(str)
        fig = go.Figure()
        fig.add_bar(x=x, y=d["disponible"].clip(lower=0), name="Disponible", marker_color=TINTA)
        fig.add_bar(x=x, y=d["entrante"], name="Entrante", marker_color=GRIS)
        fig.add_bar(x=x, y=d["u30"], name="Vendido 30d", marker_color=AZUL)
        fig.add_bar(x=x, y=d["sugerido"], name="Sugerido", marker_color=SENAL, marker_line=dict(color=TINTA, width=1.5))
        st.plotly_chart(estilo(fig, "Curva de talles", 290, barmode="group", xaxis_type="category"), width="stretch",
                        key=f"curva_{pref}_{fila['tienda']}_{fila['modelo_color']}")

        skus = set(d["sku"])
        vv = ventas[(ventas["tienda"] == fila["tienda"]) & ventas["sku"].isin(skus)]
        serie = vv.groupby("fecha")["unidades"].sum().reindex(
            pd.date_range(pd.Timestamp(hoy) - pd.Timedelta(days=90), pd.Timestamp(hoy)), fill_value=0)
        fig2 = go.Figure()
        fig2.add_bar(x=serie.index, y=serie.values, name="Unidades/día", marker_color="rgba(10,10,10,.22)")
        fig2.add_scatter(x=serie.index, y=serie.rolling(7, min_periods=1).mean(), name="Media 7d", line=dict(color=SENAL, width=3))
        if not hist.empty:
            hh = hist[(hist["tienda"] == fila["tienda"]) & hist["sku"].isin(skus)].groupby("fecha")["disponible"].sum()
            if not hh.empty:
                fig2.add_scatter(x=hh.index, y=hh.values, name="Stock", yaxis="y2", line=dict(color=AZUL, width=2, dash="dot"))
        st.plotly_chart(estilo(fig2, "Ventas diarias 90d vs stock", 270,
                               yaxis2=dict(overlaying="y", side="right", showgrid=False, linecolor=TINTA, linewidth=2)), width="stretch",
                        key=f"serie_{pref}_{fila['tienda']}_{fila['modelo_color']}")
    seccion("Desglose por SKU", f"{len(d)} talles")
    tabla(d, [c for c in COLS_SKU if c not in ("img_url", "marca", "producto", "color", "url_admin")], key=f"det_{pref}_{fila['tienda']}_{fila['modelo_color']}")


def tarjeta(fila, talles):
    """HTML de la tarjeta de un Modelo+Color para la vitrina."""
    est = fila["estado_rep"]
    col = COLOR_ESTADO.get(est, PAPEL)
    txt = PAPEL if col in (TINTA, AZUL) else TINTA
    tl = "".join(
        f'<span class="{"on" if dsp > 0 else ("br" if dem > 0 else "off")}">{t}</span>' for t, dsp, dem in talles)
    cob = num(fila["cobertura_dias"]) if np.isfinite(fila["cobertura_dias"]) else "∞"
    rp = (f'<div class="rp"><span>Reponer</span><span>{num(fila["sugerido"])} uds</span></div>' if fila["sugerido"] > 0
          else '<div class="rp no"><span>Sin reposición</span><span>—</span></div>')
    return (f'<div class="card"><div class="ph"><img src="{fila["img_url"]}" loading="lazy"></div>'
            f'<div class="badge" style="background:{col};color:{txt}">{est[2:]}</div><div class="abc">{fila["abc"]}</div>'
            f'<div class="bd"><div class="nm">{fila["producto"]}</div>'
            f'<div class="cd">{fila["marca"]} · {fila["modelo_color"]} · {fila["color"]}</div>'
            f'<div class="tl">{tl}</div>'
            f'<div class="st"><div>Vel/día<b>{num(fila["velocidad"], 1)}</b></div><div>Cobert.<b>{cob}d</b></div>'
            f'<div>Disp.<b>{num(fila["disponible"])}</b></div></div></div>{rp}</div>')


def talles_de(tienda, mc):
    d = sku[(sku["tienda"] == tienda) & (sku["modelo_color"] == mc)]
    filas = sorted(zip(d["talle"].astype(str), d["disponible"], d["u90"]), key=lambda x: core.clave_talle(x[0]))
    return filas


# ==============================================================================
# TABS
# ==============================================================================
tab_al, tab_vit, tab_mod, tab_sku, tab_plan, tab_ana, tab_tend = st.tabs(
    ["01 · Alertas", "02 · Vitrina", "03 · Modelo + Color", "04 · SKU", "05 · Plan de reposición", "06 · Análisis", "07 · Tendencias"])

# ---------------- ALERTAS ----------------
with tab_al:
    claves = list(TITULO_ALERTA)
    grilla([(f'<span class="sq" style="background:{COLOR_ALERTA[k_]}"></span>{LABEL_ALERTA[k_]}', num(len(alertas[k_])),
             {"quiebre": f"{money(alertas['quiebre']['venta_perdida_dia'].sum())}/día perdidos",
              "critico": "cobertura < lead time", "reponer": f"{num(alertas['reponer']['sugerido'].sum())} uds sugeridas",
              "curva_rota": "modelos", "acelerando": "modelos · v7/v30 alto",
              "sobrestock": money(alertas["sobrestock"]["valor_stock"].sum()),
              "sin_movimiento": money(alertas["sin_movimiento"]["valor_stock"].sum()),
              "stock_negativo": "sobreventa"}[k_],
             "hot" if k_ == "quiebre" else "") for k_ in claves])

    por_marca_estado = sku.groupby(["marca", "estado_rep"]).size().reset_index(name="skus")
    fig = go.Figure()
    for e in core.ESTADOS:
        x = por_marca_estado[por_marca_estado["estado_rep"] == e]
        fig.add_bar(y=x["marca"], x=x["skus"], name=e[2:], orientation="h", marker_color=COLOR_ESTADO[e],
                    marker_line=dict(color=TINTA, width=1))
    st.plotly_chart(estilo(fig, "Salud del surtido por marca · SKUs", 80 + 42 * max(len(marcas), 1), barmode="stack"), width="stretch")

    # Calendario de quiebres: qué se queda sin stock en los próximos 45 días
    prox = sku[(sku["velocidad"] > 0) & (sku["disponible"] > 0) & sku["fecha_quiebre"].notna()].copy()
    prox = prox[prox["fecha_quiebre"] <= pd.Timestamp(hoy) + pd.Timedelta(days=45)]
    if not prox.empty:
        prox["riesgo"] = prox["velocidad"] * prox["precio"]
        cal = prox.groupby("fecha_quiebre").agg(skus=("sku", "count"), riesgo=("riesgo", "sum")).reset_index()
        cal["riesgo_acum"] = cal["riesgo"].cumsum()
        fig = go.Figure()
        fig.add_bar(x=cal["fecha_quiebre"], y=cal["skus"], name="SKUs que se quiebran", marker_color=TINTA,
                    hovertemplate="%{x|%d/%m}<br>%{y} SKUs<extra></extra>")
        fig.add_scatter(x=cal["fecha_quiebre"], y=cal["riesgo_acum"], name="Venta diaria en riesgo (acum.)", yaxis="y2",
                        line=dict(color=SENAL, width=3, shape="hv"), hovertemplate="%{x|%d/%m}<br>$%{y:,.0f}/día<extra></extra>")
        fig.add_vline(x=pd.Timestamp(hoy) + pd.Timedelta(days=int(lead_time)), line=dict(color=SENAL, dash="dash", width=2))
        fig.add_annotation(x=pd.Timestamp(hoy) + pd.Timedelta(days=int(lead_time)), y=1, yref="paper", text=" LLEGA UN PEDIDO DE HOY",
                           showarrow=False, xanchor="left", font=dict(size=10, color=SENAL))
        st.plotly_chart(estilo(fig, f"Calendario de quiebres · próximos 45 días · {num(len(prox))} SKUs", 300,
                               yaxis2=dict(overlaying="y", side="right", showgrid=False, linecolor=TINTA, linewidth=2, rangemode="tozero"),
                               yaxis=dict(rangemode="tozero")),
                        width="stretch")

    sub = st.tabs([f"{LABEL_ALERTA[k_]} ({len(alertas[k_])})" for k_ in claves])
    for t, k_ in zip(sub, claves):
        with t:
            df = alertas[k_]
            if df.empty:
                st.markdown("**— Sin casos —**")
                continue
            tabla(df, COLS_MOD if k_ in ("curva_rota", "acelerando") else COLS_SKU, key=f"al_{k_}", height=450)
            st.download_button("⬇️ Descargar Excel", a_excel({k_: df.drop(columns=["img_url"], errors="ignore")}),
                               f"alerta_{k_}_{hoy}.xlsx", key=f"dl_{k_}")

# ---------------- VITRINA ----------------
with tab_vit:
    v1, v2, v3, v4 = st.columns([2, 2, 1.3, 1])
    vq = v1.text_input("Buscar", key="q_vit", placeholder="código, nombre o color")
    vest = v2.multiselect("Estado", core.ESTADOS, default=core.ESTADOS[:3], key="est_vit")
    vord = v3.selectbox("Ordenar por", ["Venta perdida", "Velocidad", "Sugerido", "Cobertura ↑", "Tendencia", "Valor stock"], key="ord_vit")
    vxp = v4.selectbox("Por página", [12, 24, 48], index=1, key="pp_vit")
    vf = mod.copy()
    if vq:
        qq = vq.lower()
        vf = vf[vf[["modelo_color", "producto", "color"]].astype(str).apply(lambda c: c.str.lower().str.contains(qq, regex=False)).any(axis=1)]
    if vest:
        vf = vf[vf["estado_rep"].isin(vest)]
    oc = {"Venta perdida": ("venta_perdida_dia", False), "Velocidad": ("velocidad", False), "Sugerido": ("sugerido", False),
          "Cobertura ↑": ("cobertura_dias", True), "Tendencia": ("tendencia", False), "Valor stock": ("valor_stock", False)}[vord]
    vf = vf.sort_values(oc[0], ascending=oc[1]).reset_index(drop=True)
    paginas = max(1, int(np.ceil(len(vf) / vxp)))
    pc1, pc2 = st.columns([4, 1])
    pag = pc2.number_input(f"Página (de {paginas})", 1, paginas, 1, key="pag_vit")
    pc1.markdown(f'<div class="legend-tl">{num(len(vf))} modelos · talles: <span style="background:#0A0A0A"></span>con stock'
                 f'<span style="background:#FF4F00;border-color:#FF4F00"></span>quebrado con demanda'
                 f'<span style="border-color:#D8D0BF"></span>sin stock sin demanda</div>', unsafe_allow_html=True)

    sel_key = "vit_sel"
    if st.session_state.get(sel_key) is not None:
        t_, mc_ = st.session_state[sel_key]
        fsel = mod[(mod["tienda"] == t_) & (mod["modelo_color"] == mc_)]
        if not fsel.empty:
            hc1, hc2 = st.columns([6, 1])
            hc1.markdown(f'<div class="sec">Ficha · {mc_}<small>seleccionado desde la vitrina</small></div>', unsafe_allow_html=True)
            if hc2.button("✕ Cerrar", key="vit_close", width="stretch"):
                st.session_state[sel_key] = None
                st.rerun()
            detalle_modelo(fsel.iloc[0], pref="vit")
            st.divider()

    page = vf.iloc[(pag - 1) * vxp: pag * vxp]
    ncol = 4
    for i in range(0, len(page), ncol):
        cols = st.columns(ncol, gap="medium")
        for c, (_, fila) in zip(cols, page.iloc[i:i + ncol].iterrows()):
            c.markdown(tarjeta(fila, talles_de(fila["tienda"], fila["modelo_color"])), unsafe_allow_html=True)
            if c.button("Ver ficha →", key=f"vb_{fila['tienda']}_{fila['modelo_color']}", width="stretch"):
                st.session_state[sel_key] = (fila["tienda"], fila["modelo_color"])
                st.rerun()

# ---------------- ANÁLISIS ----------------
with tab_ana:
    # 1) Matriz velocidad × cobertura (interactiva: seleccioná con caja o lazo)
    seccion("Matriz velocidad × cobertura", "arrastrá para seleccionar modelos · doble clic para resetear")
    mm = mod[(mod["velocidad"] > 0)].copy()
    mm = mm.sort_values("vta90", ascending=False).head(1500)
    mm["cob_plot"] = mm["cobertura_dias"].replace(np.inf, 400).clip(0.5, 400)
    mm["tam"] = np.sqrt(mm["valor_stock"].clip(lower=0) + 1)
    mm["tam"] = 6 + 34 * mm["tam"] / max(mm["tam"].max(), 1)
    fig = go.Figure()
    for e in core.ESTADOS:
        x = mm[mm["estado_rep"] == e]
        if x.empty:
            continue
        fig.add_scatter(x=x["velocidad"], y=x["cob_plot"], mode="markers", name=e[2:],
                        marker=dict(size=x["tam"], color=COLOR_ESTADO[e], line=dict(color=TINTA, width=1), opacity=.85),
                        customdata=np.stack([x["tienda"], x["modelo_color"], x["producto"], x["disponible"], x["sugerido"]], axis=-1),
                        hovertemplate="<b>%{customdata[2]}</b><br>%{customdata[1]}<br>Vel %{x:.2f}/día · Cob %{y:.0f}d"
                                      "<br>Disp %{customdata[3]} · Reponer %{customdata[4]}<extra></extra>")
    lt_ = int(lead_time)
    fig.add_hline(y=lt_, line=dict(color=SENAL, dash="dash", width=2))
    fig.add_hline(y=float(dias_sobre), line=dict(color=AZUL, dash="dash", width=2))
    vmed = float(mm["velocidad"].median()) if not mm.empty else 1
    fig.add_vline(x=vmed, line=dict(color=GRIS, dash="dot", width=1.5))
    for tx, xx, yy, xa, ya in [("REPONER YA", 0.99, 0.02, "right", "bottom"), ("LIQUIDAR", 0.01, 0.98, "left", "top"),
                               ("SOBRECOMPRADOS", 0.99, 0.98, "right", "top"), ("COLA LARGA", 0.01, 0.02, "left", "bottom")]:
        fig.add_annotation(x=xx, y=yy, xref="paper", yref="paper", text=tx, showarrow=False, xanchor=xa, yanchor=ya,
                           font=dict(family="Space Grotesk, sans-serif", size=18, color="rgba(10,10,10,.28)"))
    estilo(fig, "", 520, dragmode="select")
    fig.update_xaxes(type="log", title="velocidad (uds/día) →", tickvals=[0.01, 0.03, 0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 50],
                     ticktext=["0,01", "0,03", "0,1", "0,25", "0,5", "1", "2", "5", "10", "20", "50"])
    fig.update_yaxes(type="log", title="cobertura (días) →", tickvals=[1, 7, 15, 30, 60, 90, 180, 365],
                     ticktext=["1", "7", "15", "30", "60", "90", "180", "365+"])
    ev_m = st.plotly_chart(fig, width="stretch", on_select="rerun", selection_mode=("box", "lasso"), key="matriz")
    puntos = (ev_m.selection.points if ev_m is not None and hasattr(ev_m, "selection") else []) or []
    if puntos:
        claves_sel = {(p["customdata"][0], p["customdata"][1]) for p in puntos if p.get("customdata")}
        sel = mod[[(t, m) in claves_sel for t, m in zip(mod["tienda"], mod["modelo_color"])]]
        grilla([("Modelos seleccionados", num(len(sel)), "", "ink"), ("Stock", num(sel["disponible"].sum()), money(sel["valor_stock"].sum()), ""),
                ("A reponer", num(sel["sugerido"].sum()), "uds sugeridas", "hot")], cols=3)
        tabla(sel.sort_values("velocidad", ascending=False), COLS_MOD, key="tabla_matriz", height=360)
        st.download_button("⬇️ Excel de la selección", a_excel({"seleccion": sel.drop(columns=["img_url"], errors="ignore")}),
                           f"seleccion_matriz_{hoy}.xlsx", key="dl_matriz")

    # 2) Treemap: dónde está la plata (stock valorizado), color = cobertura
    seccion("Dónde está el stock", "clic para entrar en marca → tipo → modelo · color = días de cobertura")
    tm = mod[mod["valor_stock"] > 0].copy()
    tm["tipo"] = tm["tipo"].replace("", "Sin tipo").fillna("Sin tipo")
    tm = tm.sort_values("valor_stock", ascending=False).groupby("marca").head(150)
    tm["cob_c"] = tm["cobertura_dias"].replace(np.inf, 365).clip(0, 365)
    if not tm.empty:
        import plotly.express as px
        figt = px.treemap(tm, path=[px.Constant("Total"), "marca", "tipo", "modelo_color"], values="valor_stock", color="cob_c",
                          color_continuous_scale=[[0, SENAL], [0.12, "#FFD000"], [0.3, PAPEL], [1, AZUL]], range_color=(0, 365),
                          hover_data={"producto": True, "disponible": True, "velocidad": ":.2f", "cob_c": ":.0f"})
        figt.update_traces(marker=dict(line=dict(color=TINTA, width=1.5)), root_color=PAPEL,
                           texttemplate="<b>%{label}</b><br>%{value:$,.0f}", textfont=dict(family="IBM Plex Mono, monospace", size=11))
        figt.update_layout(coloraxis_colorbar=dict(title="días", thickness=12))
        st.plotly_chart(estilo(figt, "", 520), width="stretch")

    # 3) Mapa de calor de talles
    seccion("Mapa de talles", "cobertura en días por talle · los modelos que más venden")
    h1, h2 = st.columns([2, 1])
    hm_marca = h1.selectbox("Marca", sorted(mod["marca"].unique()), key="hm_marca")
    hm_n = h2.slider("Modelos", 10, 60, 25, 5, key="hm_n")
    top_m = mod[mod["marca"] == hm_marca].sort_values("velocidad", ascending=False).head(hm_n)
    dh = sku[(sku["marca"] == hm_marca) & sku["modelo_color"].isin(top_m["modelo_color"])].copy()
    if not dh.empty:
        dh["talle"] = dh["talle"].astype(str)
        dh["cob"] = np.where(dh["velocidad"] > 0, dh["disponible"].clip(lower=0) / dh["velocidad"],
                             np.where(dh["disponible"] > 0, 120, np.nan))
        piv = dh.pivot_table(index="modelo_color", columns="talle", values="cob", aggfunc="mean")
        txt = dh.pivot_table(index="modelo_color", columns="talle", values="disponible", aggfunc="sum")
        cols_t = sorted(piv.columns, key=core.clave_talle)
        orden_m = [m for m in top_m["modelo_color"] if m in piv.index]
        piv, txt = piv.reindex(index=orden_m, columns=cols_t), txt.reindex(index=orden_m, columns=cols_t)
        figh = go.Figure(go.Heatmap(z=piv.clip(upper=120).values, x=cols_t, y=piv.index, zmin=0, zmax=120,
                                    text=txt.fillna("").values, texttemplate="%{text}", textfont=dict(size=10),
                                    colorscale=[[0, SENAL], [0.25, "#FFD000"], [0.5, PAPEL], [1, AZUL]], xgap=2, ygap=2,
                                    hovertemplate="%{y} · talle %{x}<br>cobertura %{z:.0f} días · disp %{text}<extra></extra>",
                                    colorbar=dict(title="días", thickness=12)))
        estilo(figh, "", 40 + 26 * len(orden_m))
        figh.update_yaxes(autorange="reversed", type="category")
        figh.update_xaxes(type="category", side="top")
        st.plotly_chart(figh, width="stretch")

    # 4) Comparativo por marca
    seccion("Comparativo por marca")
    cm = sku.groupby("marca").agg(skus=("sku", "count"), u30=("u30", "sum"), vta30=("vta30", "sum"),
                                  disp=("disponible", lambda x: x.clip(lower=0).sum()), vel=("velocidad", "sum"),
                                  quiebres=("estado_rep", lambda x: int((x == core.ESTADOS[0]).sum())),
                                  perdida=("venta_perdida_dia", "sum"), valor=("valor_stock", "sum")).reset_index()
    cm["cobertura"] = cm["disp"] / cm["vel"].replace(0, np.nan)
    cm["sell_through"] = cm["u30"] / (cm["u30"] + cm["disp"]).replace(0, np.nan)
    cm["pct_quiebre"] = cm["quiebres"] / cm["skus"]
    figc = go.Figure()
    figc.add_bar(x=cm["marca"], y=cm["sell_through"], name="Sell-through 30d", marker_color=TINTA, yaxis="y",
                 hovertemplate="%{x}<br>%{y:.0%}<extra></extra>")
    figc.add_bar(x=cm["marca"], y=cm["pct_quiebre"], name="% SKUs en quiebre", marker_color=SENAL,
                 hovertemplate="%{x}<br>%{y:.0%}<extra></extra>")
    figc.add_scatter(x=cm["marca"], y=cm["cobertura"], name="Cobertura (días)", yaxis="y2", mode="markers+lines",
                     marker=dict(size=12, symbol="square", color=AZUL, line=dict(color=TINTA, width=1.5)), line=dict(color=AZUL, width=2))
    st.plotly_chart(estilo(figc, "", 360, barmode="group", yaxis=dict(tickformat=".0%"),
                           yaxis2=dict(overlaying="y", side="right", showgrid=False, title="días", linecolor=TINTA, linewidth=2,
                                       rangemode="tozero")),
                    width="stretch")
    st.dataframe(cm[["marca", "skus", "u30", "vta30", "disp", "valor", "cobertura", "sell_through", "quiebres", "perdida"]],
                 hide_index=True, width="stretch",
                 column_config={"marca": "Marca", "skus": "SKUs", "u30": "Uds 30d",
                                "vta30": st.column_config.NumberColumn("Venta 30d", format="localized"), "disp": "Disp.",
                                "valor": st.column_config.NumberColumn("Valor stock", format="localized"),
                                "cobertura": st.column_config.NumberColumn("Cobertura (d)", format="%.0f"),
                                "sell_through": st.column_config.ProgressColumn("Sell-through 30d", format="percent", min_value=0, max_value=1),
                                "quiebres": "En quiebre",
                                "perdida": st.column_config.NumberColumn("Venta perdida/día", format="localized")})

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
                                         "costo": st.column_config.NumberColumn("Costo", format="localized")})
    final = edit[edit["pedir"] & (edit["a_pedir"] > 0)].copy()
    final["valor"] = final["a_pedir"] * final["costo"].fillna(final["precio"])
    res = final.groupby("marca").agg(skus=("sku", "count"), unidades=("a_pedir", "sum"), valor=("valor", "sum")).reset_index()
    grilla([("SKUs en el pedido", num(len(final)), "seleccionados", "ink"),
            ("Unidades", num(final["a_pedir"].sum()), "a pedir", ""),
            ("Valor del pedido", money(final["valor"].sum()), "a costo", "hot")], cols=3)
    st.dataframe(res, hide_index=True, width="stretch",
                 column_config={"valor": st.column_config.NumberColumn("Valor", format="localized")})
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
        for i, (m_, g) in enumerate(sem.groupby("marca")):
            fig.add_scatter(x=g["semana"], y=g["unidades"], name=m_, mode="lines+markers",
                            line=dict(color=COLOR_MARCAS[i % len(COLOR_MARCAS)], width=2.5),
                            marker=dict(size=6, symbol="square"))
        st.plotly_chart(estilo(fig, "Unidades por semana · semanas cerradas", 340), width="stretch")
    c1, c2 = st.columns(2)
    with c1:
        seccion("▲ Aceleran", "top 20 · v7 vs v30")
        tabla(mod[mod["u7"] >= 3].sort_values("tendencia", ascending=False).head(20),
              ["img_url", "marca", "modelo_color", "producto", "u7", "u30", "tendencia", "disponible", "cobertura_dias", "estado_rep"], key="t_up")
    with c2:
        seccion("▼ Desaceleran", "top 20")
        tabla(mod[mod["u30"] >= 10].sort_values("tendencia").head(20),
              ["img_url", "marca", "modelo_color", "producto", "u7", "u30", "tendencia", "disponible", "cobertura_dias", "estado_rep"], key="t_down")
    seccion("Top 30 por velocidad", "modelo + color")
    tabla(mod.sort_values("velocidad", ascending=False).head(30), COLS_MOD, key="t_top")

st.caption("Velocidad = 0,5·v14 + 0,3·v30 + 0,2·v60 descontando días sin stock · Stock seguridad = z(ABC)·σ·√LT · "
           "Punto de pedido = vel·LT + SS · Objetivo = vel·(LT+cobertura) + SS")
