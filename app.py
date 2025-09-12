import os
import requests
import datetime
import dash
from dash import dcc, html
import dash_bootstrap_components as dbc
import plotly.graph_objs as go

# === API TOKENS ===
POSTER_TOKEN = os.getenv("POSTER_TOKEN", "687409:4164553abf6a031302898da7800b59fb")
CHOICE_TOKEN = os.getenv("CHOICE_TOKEN", "VlFmffA-HWXnYEm-cOXRIze-FDeVdAw")

# === CATEGORY IDS ===
HOT_CATEGORIES = {
    "ЧЕБУРЕКИ": 4,
    "МЯСНІ СТРАВИ": 13,
    "ЯНТИКИ": 15,
    "ГОРЯЧІ СТРАВИ": 46,
    "ПИДЕ": 33
}
COLD_CATEGORIES = {
    "МАНТЫ": 7,
    "ДЕРУНИ": 8,
    "САЛАТИ": 11,
    "СУПИ": 16,
    "МЛИНЦІ та СИРНИКИ": 18,
    "ЗАКУСКИ": 19,
    "ПІСНЕ МЕНЮ": 29,
    "ДЕСЕРТИ": 32,
    "СНІДАНКИ": 36,
    "Власне виробництво": 44
}

# === FETCH SALES BY CATEGORY ===
def get_category_sales(date_from, date_to):
    url = f"https://poka-net3.joinposter.com/api/dash.getCategoriesSales"
    params = {"token": POSTER_TOKEN, "dateFrom": date_from, "dateTo": date_to}
    r = requests.get(url, params=params)
    data = r.json().get("response", [])
    return {int(item["category_id"]): float(item["count"]) for item in data}

# === FETCH BOOKINGS ===
def get_bookings():
    url = "https://poka-net3.choiceqr.com/api/bookings/list"
    headers = {"Authorization": f"Bearer {CHOICE_TOKEN}"}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            data = r.json()
            return len(data.get("response", [])) if isinstance(data, dict) else 0
    except Exception:
        return 0
    return 0

# === HOURLY SALES (transactions.getTransactions) ===
def get_hourly_sales(date_from, date_to):
    url = "https://poka-net3.joinposter.com/api/transactions.getTransactions"
    params = {
        "token": POSTER_TOKEN,
        "date_from": date_from,
        "date_to": date_to,
        "per_page": 500,
        "page": 1
    }
    r = requests.get(url, params=params)
    data = r.json().get("response", {}).get("data", [])

    hot_counts = {}
    cold_counts = {}

    for tr in data:
        hour = datetime.datetime.strptime(tr["date_close"], "%Y-%m-%d %H:%M:%S").hour
        for p in tr.get("products", []):
            cat_id = p.get("workshop_id")
            num = float(p.get("num", 0))
            if cat_id in HOT_CATEGORIES.values():
                hot_counts[hour] = hot_counts.get(hour, 0) + num
            elif cat_id in COLD_CATEGORIES.values():
                cold_counts[hour] = cold_counts.get(hour, 0) + num

    return hot_counts, cold_counts

# === AGGREGATED SALES BLOCKS ===
def build_sales_blocks(today_sales):
    hot_total = {k: today_sales.get(v, 0) for k, v in HOT_CATEGORIES.items()}
    cold_total = {k: today_sales.get(v, 0) for k, v in COLD_CATEGORIES.items()}

    hot_block = dbc.Card(
        dbc.CardBody([
            html.H4("🔥 Гарячий цех", className="text-center"),
            dbc.Table(
                [html.Tr([html.Td(k), html.Td(int(v))]) for k, v in hot_total.items()],
                bordered=False, striped=False, hover=False, responsive=True
            )
        ]), className="h-100 text-white bg-dark border border-danger rounded-3"
    )

    cold_block = dbc.Card(
        dbc.CardBody([
            html.H4("❄️ Холодний цех", className="text-center"),
            dbc.Table(
                [html.Tr([html.Td(k), html.Td(int(v))]) for k, v in cold_total.items()],
                bordered=False, striped=False, hover=False, responsive=True
            )
        ]), className="h-100 text-white bg-dark border border-primary rounded-3"
    )

    bookings_block = dbc.Card(
        dbc.CardBody([
            html.H4("📖 Бронювання", className="text-center"),
            html.H2(get_bookings(), className="text-center text-success fw-bold")
        ]), className="h-100 text-white bg-dark border border-success rounded-3"
    )

    return hot_block, cold_block, bookings_block

# === BUILD GRAPH ===
def build_graph(today, last_week):
    hours = list(range(10, 23))
    now_hour = datetime.datetime.now().hour
    limit_hour = min(now_hour, 22)

    hot_today, cold_today = get_hourly_sales(today, today)
    hot_last, cold_last = get_hourly_sales(last_week, last_week)

    hot_cum, cold_cum = [], []
    hot_last_cum, cold_last_cum = [], []

    hot_sum = cold_sum = hot_last_sum = cold_last_sum = 0
    for h in hours:
        if h <= limit_hour:
            hot_sum += hot_today.get(h, 0)
            cold_sum += cold_today.get(h, 0)
        hot_cum.append(hot_sum)

        if h <= 22:
            hot_last_sum += hot_last.get(h, 0)
            cold_last_sum += cold_last.get(h, 0)
        hot_last_cum.append(hot_last_sum)
        cold_last_cum.append(cold_last_sum)
        cold_cum.append(cold_sum)

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=hours, y=hot_cum, mode="lines+markers",
                             line=dict(color="orange", width=3),
                             name="Гарячий (сьогодні)"))
    fig.add_trace(go.Scatter(x=hours, y=cold_cum, mode="lines+markers",
                             line=dict(color="skyblue", width=3),
                             name="Холодний (сьогодні)"))
    fig.add_trace(go.Scatter(x=hours, y=hot_last_cum, mode="lines",
                             line=dict(color="orange", dash="dot", width=2),
                             name="Гарячий (мин. тиждень)"))
    fig.add_trace(go.Scatter(x=hours, y=cold_last_cum, mode="lines",
                             line=dict(color="skyblue", dash="dot", width=2),
                             name="Холодний (мин. тиждень)"))

    fig.update_layout(
        title="📊 Завантаженість кухні",
        xaxis=dict(title="Година", dtick=1, range=[10, 22]),
        yaxis=dict(title="Кількість замовлень (накопич.)"),
        plot_bgcolor="#111", paper_bgcolor="#111",
        font=dict(color="white"), height=350
    )
    return dcc.Graph(figure=fig)

# === DASH APP ===
app = dash.Dash(__name__, external_stylesheets=[dbc.themes.CYBORG])

def serve_layout():
    today = datetime.date.today()
    last_week = today - datetime.timedelta(days=7)
    date_today = today.strftime("%Y%m%d")
    date_last = last_week.strftime("%Y%m%d")

    today_sales = get_category_sales(date_today, date_today)
    hot_block, cold_block, bookings_block = build_sales_blocks(today_sales)
    graph_block = build_graph(today.strftime("%Y-%m-%d"), last_week.strftime("%Y-%m-%d"))

    return dbc.Container([
        dbc.Row([
            dbc.Col(hot_block, md=4),
            dbc.Col(cold_block, md=4),
            dbc.Col(bookings_block, md=4)
        ], className="mb-4"),
        dbc.Row([dbc.Col(graph_block, md=12)])
    ], fluid=True)

app.layout = serve_layout

if __name__ == "__main__":
    app.run_server(host="0.0.0.0", port=5000, debug=True)
