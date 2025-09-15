import os
import requests
import datetime
import pytz
import dash
from dash import dcc, html
from dash.dependencies import Output, Input
import plotly.graph_objs as go

# =============== НАСТРОЙКИ ===============
POSTER_TOKEN = os.getenv("POSTER_TOKEN", "ВАШ_ТОКЕН")
POSTER_API = "https://poka-net3.joinposter.com/api"
CHOICE_API = "https://poka-net3.choiceqr.com/api"

LOCAL_TZ = pytz.timezone("Europe/Kiev")  # Измени на Europe/Sofia если нужно
# ========================================

# Категории горячего и холодного цеха
HOT_CATEGORIES = {"4": "ЧЕБУРЕКИ", "13": "МЯСНІ СТРАВИ", "15": "ЯНТИКИ", "46": "ГОРЯЧІ СТРАВИ", "33": "ПИДЕ"}
COLD_CATEGORIES = {"7": "МАНТЫ", "8": "ДЕРУНИ", "11": "САЛАТИ", "16": "СУПИ", "18": "МЛИНЦІ та СИРНИКИ",
                   "19": "ЗАКУСКИ", "29": "ПІСНЕ МЕНЮ", "32": "ДЕСЕРТИ", "36": "СНІДАНКИ", "44": "Власне виробництво"}


def fetch_categories_sales(date_from, date_to):
    url = f"{POSTER_API}/dash.getCategoriesSales?token={POSTER_TOKEN}&dateFrom={date_from}&dateTo={date_to}"
    r = requests.get(url)
    return r.json().get("response", [])


def fetch_transactions(date_from, date_to):
    url = f"{POSTER_API}/transactions.getTransactions?token={POSTER_TOKEN}&date_from={date_from}&date_to={date_to}&per_page=500"
    r = requests.get(url)
    return r.json().get("response", {}).get("data", [])


def build_hourly_data(transactions):
    hourly_hot = {}
    hourly_cold = {}

    for txn in transactions:
        close_time = datetime.datetime.strptime(txn["date_close"], "%Y-%m-%d %H:%M:%S")
        utc_time = pytz.utc.localize(close_time)
        local_time = utc_time.astimezone(LOCAL_TZ)

        hour = local_time.hour

        for product in txn.get("products", []):
            cat_id = str(product.get("workshop_id", ""))
            num = float(product.get("num", 0))

            if cat_id in HOT_CATEGORIES:
                hourly_hot[hour] = hourly_hot.get(hour, 0) + num
            elif cat_id in COLD_CATEGORIES:
                hourly_cold[hour] = hourly_cold.get(hour, 0) + num

    hours = list(range(10, 23))
    hot_cumulative, cold_cumulative = [], []
    hot_total, cold_total = 0, 0

    for h in hours:
        hot_total += hourly_hot.get(h, 0)
        cold_total += hourly_cold.get(h, 0)
        hot_cumulative.append(hot_total)
        cold_cumulative.append(cold_total)

    return hours, hot_cumulative, cold_cumulative


# ================== DASH ==================
app = dash.Dash(__name__)
server = app.server

app.layout = html.Div([
    html.Div([
        html.Div(id="hot-block", className="block"),
        html.Div(id="cold-block", className="block"),
        html.Div(id="bookings-block", className="block"),
    ], className="row"),

    html.Div([
        html.H3("📊 Завантаженість кухні", style={"textAlign": "center"}),
        dcc.Graph(id="kitchen-load")
    ], className="graph-block"),

    dcc.Interval(id="interval", interval=60 * 1000, n_intervals=0)
])


@app.callback(
    [Output("hot-block", "children"),
     Output("cold-block", "children"),
     Output("bookings-block", "children"),
     Output("kitchen-load", "figure")],
    [Input("interval", "n_intervals")]
)
def update_dashboard(n):
    today = datetime.datetime.now(LOCAL_TZ).strftime("%Y%m%d")
    last_week = (datetime.datetime.now(LOCAL_TZ) - datetime.timedelta(days=7)).strftime("%Y%m%d")

    # --- Блок продаж ---
    sales_today = fetch_categories_sales(today, today)

    hot_sales = {HOT_CATEGORIES[c["category_id"]]: int(float(c["count"]))
                 for c in sales_today if c["category_id"] in HOT_CATEGORIES}
    cold_sales = {COLD_CATEGORIES[c["category_id"]]: int(float(c["count"]))
                  for c in sales_today if c["category_id"] in COLD_CATEGORIES}

    hot_block = [html.H3("🔥 Гарячий цех")] + [html.Div(f"{k}: {v}") for k, v in hot_sales.items()]
    cold_block = [html.H3("❄️ Холодний цех")] + [html.Div(f"{k}: {v}") for k, v in cold_sales.items()]

    # --- Бронирования ---
    bookings_block = [html.H3("📅 Бронювання"),
                      html.Div("Загальна кількість замовлень: 0")]

    # --- Диаграмма ---
    today_tx = fetch_transactions(today, today)
    week_tx = fetch_transactions(last_week, last_week)

    hours, hot_today, cold_today = build_hourly_data(today_tx)
    _, hot_week, cold_week = build_hourly_data(week_tx)

    now_hour = datetime.datetime.now(LOCAL_TZ).hour
    cutoff = max(10, min(now_hour, 22))

    hours_cut = [h for h in hours if h <= cutoff]
    hot_today_cut = hot_today[:len(hours_cut)]
    cold_today_cut = cold_today[:len(hours_cut)]

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=hours_cut, y=hot_today_cut, mode="lines+markers",
                             name="Гарячий сьогодні", line=dict(color="orange", width=3)))
    fig.add_trace(go.Scatter(x=hours_cut, y=cold_today_cut, mode="lines+markers",
                             name="Холодний сьогодні", line=dict(color="skyblue", width=3)))
    fig.add_trace(go.Scatter(x=hours, y=hot_week, mode="lines", name="Гарячий мин.тиждень",
                             line=dict(color="orange", dash="dot")))
    fig.add_trace(go.Scatter(x=hours, y=cold_week, mode="lines", name="Холодний мин.тиждень",
                             line=dict(color="skyblue", dash="dot")))

    fig.update_layout(template="plotly_dark",
                      xaxis=dict(title="Година", range=[10, 22]),
                      yaxis=dict(title="Кількість замовлень (накопич.)"),
                      margin=dict(l=20, r=20, t=20, b=20),
                      legend=dict(orientation="h", y=1.1, x=0.3))

    return hot_block, cold_block, bookings_block, fig


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
