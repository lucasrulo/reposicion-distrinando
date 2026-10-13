"""
Digest diario de alertas de reposición.
Lo corre GitHub Actions a las 8:00 (ARG) después de sincronizar. Envía por:
  - Email (SMTP, ej. Gmail con contraseña de aplicación): SMTP_USER, SMTP_PASS, ALERTAS_DESTINO (separados por coma)
  - Slack (opcional): SLACK_WEBHOOK
Si no hay secrets configurados, solo imprime el resumen en el log.
"""
import json
import os
import smtplib
from datetime import date
from email.mime.text import MIMEText

import numpy as np
import pandas as pd
import requests

import core

DATA_DIR = os.environ.get("DATA_DIR", "data")
DASHBOARD_URL = os.environ.get("DASHBOARD_URL", "")
TOP = 15


def money(x):
    return "$" + f"{x:,.0f}".replace(",", ".")


def tabla_html(df, cols, nombres):
    if df.empty:
        return "<p style='color:#16a34a'>Sin casos 👌</p>"
    d = df.head(TOP)[cols].copy()
    for c in d.columns:
        if d[c].dtype.kind == "f":
            d[c] = d[c].map(lambda x: "∞" if not np.isfinite(x) else f"{x:,.1f}".replace(",", "X").replace(".", ",").replace("X", "."))
    d.columns = nombres
    extra = f"<p style='color:#64748b;font-size:12px'>…y {len(df) - TOP} más en el dashboard</p>" if len(df) > TOP else ""
    return d.to_html(index=False, border=0, classes="t") + extra


def main():
    ventas = pd.read_parquet(f"{DATA_DIR}/ventas_diarias.parquet")
    stock = pd.read_parquet(f"{DATA_DIR}/stock_actual.parquet")
    hist = pd.read_parquet(f"{DATA_DIR}/stock_historial.parquet")
    v, s, h = core.preparar(ventas, stock, hist, incluir_estados=("ACTIVE", "UNLISTED"))
    d = core.calcular_sku(v, s, h)
    m = core.calcular_modelo(d)
    a = core.resumen_alertas(d, m)

    perdida = d["venta_perdida_dia"].sum()
    resumen = {
        "quiebre": len(a["quiebre"]), "critico": len(a["critico"]), "reponer": len(a["reponer"]),
        "curva_rota": len(a["curva_rota"]), "acelerando": len(a["acelerando"]),
        "uds_sugeridas": int(d["sugerido"].sum()), "venta_perdida_dia": round(float(perdida)),
    }
    print(json.dumps(resumen, ensure_ascii=False))

    por_marca = d.groupby("marca").agg(
        quiebre=("estado_rep", lambda x: int((x == core.ESTADOS[0]).sum())),
        critico=("estado_rep", lambda x: int((x == core.ESTADOS[1]).sum())),
        sugerido=("sugerido", "sum"), perdida=("venta_perdida_dia", "sum")).reset_index()
    por_marca["perdida"] = por_marca["perdida"].map(money)

    html = f"""
    <html><head><style>
      body{{font-family:Arial,sans-serif;color:#0f172a}} h2{{margin-bottom:4px}} h3{{margin:22px 0 6px}}
      table.t{{border-collapse:collapse;font-size:12px}} .t th{{background:#0f172a;color:#fff;padding:6px 8px;text-align:left}}
      .t td{{border-bottom:1px solid #e2e8f0;padding:5px 8px}}
    </style></head><body>
    <h2>📦 Reposición Distrinando · {date.today():%d/%m/%Y}</h2>
    <p><b>{resumen['quiebre']}</b> SKUs en quiebre con demanda · <b>{resumen['critico']}</b> críticos ·
       <b>{resumen['uds_sugeridas']:,}</b> uds sugeridas · venta perdida estimada <b>{money(perdida)}/día</b></p>
    {f'<p><a href="{DASHBOARD_URL}">Abrir dashboard →</a></p>' if DASHBOARD_URL else ''}
    <h3>Por marca</h3>{tabla_html(por_marca, ['marca','quiebre','critico','sugerido','perdida'], ['Marca','Quiebre','Críticos','Uds sugeridas','Venta perdida/día'])}
    <h3>🔴 Quiebres que más venta pierden</h3>
    {tabla_html(a['quiebre'], ['marca','sku','producto','velocidad','entrante','sugerido'], ['Marca','SKU','Producto','Vel/día','Entrante','Sugerido'])}
    <h3>🟠 Se quiebran antes del lead time</h3>
    {tabla_html(a['critico'], ['marca','sku','producto','disponible','velocidad','cobertura_dias','sugerido'], ['Marca','SKU','Producto','Disp.','Vel/día','Cobertura (d)','Sugerido'])}
    <h3>🧩 Curva de talles rota</h3>
    {tabla_html(a['curva_rota'], ['marca','modelo_color','producto','talles_con_stock','talles','u30'], ['Marca','Modelo+Color','Producto','Talles c/stock','Talles','Uds 30d'])}
    <h3>🚀 Acelerando</h3>
    {tabla_html(a['acelerando'], ['marca','modelo_color','producto','u7','u30','tendencia','cobertura_dias'], ['Marca','Modelo+Color','Producto','Uds 7d','Uds 30d','v7/v30','Cobertura (d)'])}
    </body></html>"""

    user, pwd, dest = os.environ.get("SMTP_USER"), os.environ.get("SMTP_PASS"), os.environ.get("ALERTAS_DESTINO")
    if user and pwd and dest:
        msg = MIMEText(html, "html", "utf-8")
        msg["Subject"] = f"📦 Reposición: {resumen['quiebre']} quiebres · {resumen['critico']} críticos · {money(perdida)}/día perdidos"
        msg["From"], msg["To"] = user, dest
        with smtplib.SMTP_SSL(os.environ.get("SMTP_HOST", "smtp.gmail.com"), int(os.environ.get("SMTP_PORT", 465))) as srv:
            srv.login(user, pwd)
            srv.sendmail(user, [x.strip() for x in dest.split(",")], msg.as_string())
        print(f"✉️ Mail enviado a {dest}")

    hook = os.environ.get("SLACK_WEBHOOK")
    if hook:
        top = "\n".join(f"• {r.marca} `{r.sku}` {r.producto[:40]} — {r.velocidad:.1f}/día"
                        for r in a["quiebre"].head(8).itertuples())
        txt = (f"*📦 Reposición {date.today():%d/%m}*: {resumen['quiebre']} quiebres · {resumen['critico']} críticos · "
               f"{resumen['uds_sugeridas']} uds sugeridas · {money(perdida)}/día perdidos\n{top}"
               + (f"\n<{DASHBOARD_URL}|Abrir dashboard>" if DASHBOARD_URL else ""))
        requests.post(hook, json={"text": txt}, timeout=30)
        print("💬 Slack enviado")


if __name__ == "__main__":
    main()
