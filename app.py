import os
import requests
from datetime import datetime, timedelta, date
import dash
from dash import dcc, html, dash_table
import dash_bootstrap_components as dbc
import plotly.graph_objects as go

# Токен Poster API
POSTER_TOKEN = os.getenv("POSTER_TOKEN")
ACCOUNT_NAME = "poka-net3"

# Токен Choice API
CHOICE_TOKEN = os.getenv("CHOICE_TOKEN")
CHOICE_API_URL = "https://poka-net3.choiceqr.com/api/bookings/list"

# Категории горячего и холодного цеха
HOT_CATEGORIES = {4, 13, 15, 46, 33}
COLD_CATEGORIES = {7, 8, 11, 16, 18, 19, 29, 32, 36, 44}

# Инициализация Dash
app = dash.Dash(__name__, external_stylesheets=[dbc.themes.DARKLY])
server = app.server

# ===============================
# Получение продаж по категориям
# ===============================
def fetch_category_sales(date_from, date_to):
    url = f"https://{ACCOUNT_NAME}.joinposter.com/api/dash.getCategoriesSales"
    params = {"token": POSTER_TOKEN, "dateFrom": date_from, "dateTo": date_to}
    resp = requests.get(url, params=params)
    print("DEBUG GET", url, "->", resp.status_code, ":", resp.text[:300])
    try:
        return resp.json().get("response", [])
    except:
        return []

# ===============================
# Получение броней из Choice API
# ===============================
def fetch_bookings():
    try:
        resp = requests.get(CHOICE_API_URL, headers={"Authorization": f"Bearer {CHOICE_TOKEN}"}, timeout=10)
        data = resp.json()
        if "response" in data:
            bookings = []
            for b in data["response"]:
                bookings.append({
                    "name": b.get("name", "—"),
                    "time": b.get("time", "—"),
                    "guests": b.get("guests", "—"),
                })
            return bookings
    except Exception as e:
        print("ERROR Choice API:", e)
    return []

# ===============================
# Получение почасовой загрузки
# ===============================
def fetch_hourly_sales(target_date):
    url = f"https://{ACCOUNT_NAME}.joinposter.com/api/transactions.getTransactions"
    params = {
        "token": POSTER_TOKEN,
        "date_from": target_date,
        "date_to": target_date,
        "per_page": 500,
        "page": 1,
    }
    resp = requests.get(url, params=params)
    print("DEBUG GET", url, "->", resp.status_code, ":", resp.text[:300])
    try:
        data = resp.json().get("response", {}).get("data", [])
    except:
        return {}

    hourly_hot = {}
    hourly_cold = {}
    now = datetime.now()

    for t in data:
        close_time = datetime.strptime(t["date_close"], "%Y-%m-%d %H:%M:%S")
        if close_time > now:
            continue
        hour = close_time.replace(minute=0, second=0, microsecond=0)

        for p in t.get("products", []):
            cat_id = int(p.get("workshop_id", 0))
            qty = int(float(p.get("num", 0)))

            if cat_id in HOT_CATEGORIES:
                hourly_hot[hour] = hourly_hot.get(hour, 0) + qty
            elif cat_id in COLD_CATEGORIES:
                hourly_cold[hour] = hourly_cold.get(hour, 0) + qty

    # накопительные суммы
    hot_cum, cold_cum = [], []
    hot_total, cold_total = 0, 0
    for h in sorted(hourly_hot.keys() | hourly_cold.keys()):
        hot_total += hourly_hot.get(h, 0)
        cold_total += hourly_cold.get(h, 0)
        hot_cum.append((h, hot_total))
        cold_cum.append((h, cold_total))

    return {"hot": hot_cum, "cold": cold_cum}

# ===============================
# Лэйаут приложения
# ===============================
app.layout = dbc.Container(
    [
        dbc.Row(
            [
                dbc.Col(
                    dbc.Card(
                        [
                            dbc.CardHeader("🔥 Гарячий цех"),
                            dbc.CardBody(id="hot-sales"),
                        ],
                        className="h-100 border border-warning",
                    ),
                    md=4,
                ),
                dbc.Col(
                    dbc.Card(
                        [
                            dbc.CardHeader("❄️ Холодний цех"),
                            dbc.CardBody(id="cold-sales"),
                        ],
                        className="h-100 border border-info",
                    ),
                    md=4,
                ),
                dbc.Col(
                    dbc.Card(
                        [
                            dbc.CardHeader("📖 Бронювання"),
                            dbc.CardBody(id="bookings"),
                        ],
                        className="h-100 border border-light",
                    ),
                    md=4,
                ),
            ],
            className="mb-4",
        ),
        dbc.Row(
            dbc.Col(
                dbc.Card(
                    [
                        dbc.CardHeader("📊 Завантаженість кухні"),
                        dbc.CardBody(dcc.Graph(id="hourly-graph")),
                    ],
                    className="border border-secondary",
                ),
                md=12,
            )
        ),
        html.Div("GRECO", style={
            "position": "fixed",
            "bottom": "10px",
            "right": "20px",
            "fontFamily": "Inter, sans-serif",
            "fontWeight": "bold",
            "color": "white",
            "fontSize": "20px",
        }),
        dcc.Interval(id="interval", interval=60 * 1000, n_intervals=0),
    ],
    fluid=True,
)

# ===============================
# Коллбэки
# ===============================
@app.callback(
    [dash.Output("hot-sales", "children"),
     dash.Output("cold-sales", "children"),
     dash.Output("bookings", "children"),
     dash.Output("hourly-graph", "figure")],
    [dash.Input("interval", "n_intervals")],
)
def update_dashboard(_):
    today = date.today().strftime("%Y%m%d")
    last_week = (date.today() - timedelta(days=7)).strftime("%Y%m%d")

    # продажи
    sales_today = fetch_category_sales(today, today)
    hot_total = sum(int(float(c["count"])) for c in sales_today if int(c["category_id"]) in HOT_CATEGORIES)
    cold_total = sum(int(float(c["count"])) for c in sales_today if int(c["category_id"]) in COLD_CATEGORIES)

    hot_block = html.Table(
        [[html.Tr([html.Td("Всього:"), html.Td(hot_total)])]],
        className="table table-dark table-sm",
    )
    cold_block = html.Table(
        [[html.Tr([html.Td("Всього:"), html.Td(cold_total)])]],
        className="table table-dark table-sm",
    )

    # брони
    bookings = fetch_bookings()
    booking_table = dash_table.DataTable(
        columns=[
            {"name": "Імʼя", "id": "name"},
            {"name": "Час", "id": "time"},
            {"name": "Гостей", "id": "guests"},
        ],
        data=bookings,
        style_header={"backgroundColor": "black", "color": "white"},
        style_cell={"backgroundColor": "#222", "color": "white", "textAlign": "center"},
        page_size=5,
    )

    # график
    today_data = fetch_hourly_sales(today)
    last_week_data = fetch_hourly_sales(last_week)
    now = datetime.now().replace(minute=0, second=0, microsecond=0)

    hours = [datetime.combine(date.today(), datetime.min.time()) + timedelta(hours=h)
             for h in range(10, 23) if datetime.combine(date.today(), datetime.min.time()) + timedelta(hours=h) <= now]

    hot_today = []
    cold_today = []
    hot_last = []
    cold_last = []

    for h in hours:
        hot_today.append(next((v for t, v in today_data["hot"] if t == h), hot_today[-1] if hot_today else 0))
        cold_today.append(next((v for t, v in today_data["cold"] if t == h), cold_today[-1] if cold_today else 0))
        hot_last.append(next((v for t, v in last_week_data["hot"] if t == h - timedelta(days=7)), hot_last[-1] if hot_last else 0))
        cold_last.append(next((v for t, v in last_week_data["cold"] if t == h - timedelta(days=7)), cold_last[-1] if cold_last else 0))

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=hours, y=hot_today, mode="lines", name="Гарячий сьогодні", line=dict(color="orange", width=3)))
    fig.add_trace(go.Scatter(x=hours, y=cold_today, mode="lines", name="Холодний сьогодні", line=dict(color="skyblue", width=3)))
    fig.add_trace(go.Scatter(x=hours, y=hot_last, mode="lines", name="Гарячий мин.тиждень", line=dict(color="orange", dash="dot", width=2)))
    fig.add_trace(go.Scatter(x=hours, y=cold_last, mode="lines", name="Холодний мин.тиждень", line=dict(color="skyblue", dash="dot", width=2)))

    fig.update_layout(template="plotly_dark", margin=dict(l=20, r=20, t=20, b=20), height=400)

    return hot_block, cold_block, booking_table, fig

# ===============================
# Запуск
# ===============================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
