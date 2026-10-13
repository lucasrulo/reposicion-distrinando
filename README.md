# 📦 Reposición Distrinando

Dashboard de reposición para las 5 tiendas Shopify (Reebok, Columbia+MHW+Sorel, Crocs, Kappa, Piccadilly).
Muestra venta por **Modelo+Color → SKU/talle**, velocidad, cobertura, alertas y un **plan de reposición editable** que se descarga en Excel.

```
GitHub Actions (cada 2 h)                     Streamlit Cloud
extractor.py ── Bulk GraphQL ──► rama `data` ──► app.py  (core.py calcula todo en vivo con tus parámetros)
                                     │
alertas.py (07:45 lun-sáb) ──► mail / Slack
```

## Archivos
| Archivo | Qué hace |
|---|---|
| `extractor.py` | 2 bulk operations por tienda (órdenes 180 días + variantes con stock por ubicación). Guarda parquet + snapshot diario de stock |
| `core.py` | Velocidad, σ, ABC, stock de seguridad, punto de pedido, sugerido, estados y alertas |
| `app.py` | Dashboard: Alertas · Modelo+Color (clic → desglose SKU, curva de talles, ventas vs stock) · SKU · Plan de reposición · Tendencias |
| `alertas.py` | Digest diario por mail (SMTP) y/o Slack |
| `.github/workflows/sync.yml` | Corre todo y publica los datos en la rama `data` (un solo commit forzado: el repo no se infla) |

## Puesta en marcha (≈15 min)
1. **Crear repo** `lucasrulo/reposicion-distrinando` (recomendado **privado**) y subir estos archivos a `main`.
2. **Secrets del repo** (Settings → Secrets and variables → Actions):
   `TOKEN_REEBOK`, `TOKEN_COLUMBIA`, `TOKEN_CROCS`, `TOKEN_KAPPA`, `TOKEN_PICCADILLY` (los mismos del dashboard de ventas).
   Scopes necesarios de la app custom: `read_orders`, **`read_all_orders`** (sin esto Shopify solo da 60 días), `read_products`, `read_inventory`, `read_locations`.
3. Opcional alertas: `SMTP_USER`, `SMTP_PASS` (contraseña de aplicación de Gmail), `ALERTAS_DESTINO` (mails separados por coma), `SLACK_WEBHOOK`.
   Variable (no secret) `DASHBOARD_URL` con la URL de la app.
4. **Actions → Sync stock y ventas → Run workflow** (la primera vez tarda unos minutos). Verificá que aparezca la rama `data`.
5. **Streamlit Cloud → New app** → repo `reposicion-distrinando`, rama `main`, archivo `app.py`.
   Secrets: ver `.streamlit/secrets.toml.example` (si el repo es privado, un fine-grained PAT con *Contents: Read-only*).

## Cómo calcula
- **Velocidad diaria** = 0,5·v14 + 0,3·v30 + 0,2·v60. Cada ventana divide por los **días con stock** (descuenta días quebrados según el historial de snapshots y la antigüedad del producto) → un SKU que estuvo agotado no aparece como "lento".
- **Stock de seguridad** = z(nivel de servicio por ABC) · σ demanda diaria · √lead time. ABC por facturación 90 días dentro de cada marca (A 95 %, B 90 %, C 80 %).
- **Punto de pedido** = vel · LT + SS · **Stock objetivo** = vel · (LT + cobertura) + SS.
- **Sugerido** = objetivo − (disponible + entrante), solo cuando la posición está en o por debajo del punto de pedido.
- Defaults: **LT 30 días / cobertura 60 días**, editables en la barra lateral y por marca.

## Alertas
| | Regla |
|---|---|
| 🔴 Quiebre | Sin stock disponible y con demanda (muestra venta perdida estimada/día) |
| 🟠 Crítico | (disponible + entrante) / velocidad < lead time → se quiebra antes de que llegue una reposición |
| 🟡 Reponer | Posición ≤ punto de pedido |
| 🧩 Curva rota | Modelo+Color con stock pero ≥ 30 % de los talles con demanda en cero |
| 🚀 Acelerando | v7 / v30 ≥ 1,5 y ≥ 3 uds en 7 días |
| 🧊 Sobrestock | Cobertura > 180 días |
| 💤 Sin movimiento | Stock > 0, 0 ventas en 60 días, producto con > 30 días |
| ⚠️ Stock negativo | Disponible < 0 (sobreventa) |

## Notas
- **Modelo+Color** = SKU sin el último `-talle` (misma convención que el dashboard de ventas). Su estado es el **peor estado de sus talles** (un modelo con stock pero con un talle quebrado aparece en 🔴).
- Las tiendas compartidas separan marca por vendor (`MHW-ar` → Mountain Hardwear, `Sorel-ar` → Sorel). Ajustá `STORES` en `extractor.py` si cambian los handles `*.myshopify.com`.
- La corrección por días sin stock mejora a medida que se acumula el historial (se guarda 1 snapshot por día desde la primera corrida).
- Ventas = unidades netas de devoluciones (`currentQuantity`), sin órdenes canceladas ni de prueba, a precio con descuentos.
