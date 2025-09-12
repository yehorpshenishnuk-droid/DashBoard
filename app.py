import os
import time
import requests
import sys
from datetime import date, datetime
from flask import Flask, render_template_string, jsonify

app = Flask(__name__)

POSTER_TOKEN = os.getenv("POSTER_TOKEN")
CHOICE_TOKEN = os.getenv("CHOICE_TOKEN")  # токен для Choice API
ACCOUNT_NAME = "poka-net3"

# 🔥 Горячие категории
HOT_CATEGORIES = {4, 13, 15, 46, 33}
# ❄️ Холодные категории
COLD_CATEGORIES = {7, 8, 11, 16, 18, 19, 29, 32, 36, 44}

# Кэш продуктов для product_id → category_id
PRODUCT_CACHE = {}
last_products_update = 0

# Кэшированные данные
last_update = 0
cache = {"hot": {}, "cold": {}, "bookings": [], "hourly": {}}


# ======================
# Загрузка справочника продуктов
# ======================
def load_products():
    global PRODUCT_CACHE, last_products_update
    if time.time() - last_products_update < 3600 and PRODUCT_CACHE:
        return PRODUCT_CACHE

    url = f"https://{ACCOUNT_NAME}.joinposter.com/api/menu.getProducts?token={POSTER_TOKEN}&type=products"
    try:
        resp = requests.get(url, timeout=20)
        data = resp.json().get("response", [])
    except Exception as e:
        print("ERROR load_products:", e, file=sys.stderr, flush=True)
        return PRODUCT_CACHE

    mapping = {}
    for item in data:
        try:
            pid = int(item.get("product_id", 0))
            cid = int(item.get("menu_category_id", 0))
            if pid and cid:
                mapping[pid] = cid
        except Exception:
            continue

    PRODUCT_CACHE = mapping
    last_products_update = time.time()
    print(f"DEBUG Loaded {len(PRODUCT_CACHE)} products into cache", file=sys.stderr, flush=True)
    return PRODUCT_CACHE


# ======================
# Продажи по категориям (суммарные)
# ======================
def fetch_category_sales():
    today = date.today().strftime("%Y-%m-%d")
    url = (
        f"https://{ACCOUNT_NAME}.joinposter.com/api/dash.getCategoriesSales"
        f"?token={POSTER_TOKEN}&dateFrom={today}&dateTo={today}"
    )
    resp = requests.get(url, timeout=20)
    print("DEBUG Poster API:", resp.text[:500], file=sys.stderr, flush=True)

    try:
        data = resp.json().get("response", [])
    except Exception as e:
        print("ERROR parsing Poster JSON:", e, file=sys.stderr, flush=True)
        return {"hot": {}, "cold": {}}

    hot, cold = {}, {}
    for cat in data:
        try:
            cid = int(cat.get("category_id", 0))
            name = cat.get("category_name", "???")
            qty = int(float(cat.get("count", 0)))
        except Exception:
            continue

        if cid in HOT_CATEGORIES:
            hot[name] = hot.get(name, 0) + qty
        elif cid in COLD_CATEGORIES:
            cold[name] = cold.get(name, 0) + qty

    return {"hot": hot, "cold": cold}


# ======================
# Почасовая статистика по заказам
# ======================
def fetch_hourly():
    products = load_products()
    today = date.today().strftime("%Y-%m-%d")

    url = (
        f"https://{ACCOUNT_NAME}.joinposter.com/api/transactions.getTransactions"
        f"?token={POSTER_TOKEN}&date_from={today}&date_to={today}&per_page=100&page=1"
    )
    try:
        resp = requests.get(url, timeout=30)
        raw = resp.json().get("response", {}).get("data", [])
        print("DEBUG Hourly Poster API:", str(raw)[:500], file=sys.stderr, flush=True)
    except Exception as e:
        print("ERROR Hourly Poster:", e, file=sys.stderr, flush=True)
        return {"labels": [], "hot": [], "cold": []}

    hours = list(range(8, 24))
    hot_counts = [0] * len(hours)
    cold_counts = [0] * len(hours)

    for trx in raw:
        try:
            dt_str = trx.get("date_close")
            dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
            hour = dt.hour
            if hour not in hours:
                continue
            idx = hours.index(hour)
        except Exception:
            continue

        for p in trx.get("products", []):
            try:
                pid = int(p.get("product_id", 0))
                qty = int(float(p.get("num", 0)))
                cid = products.get(pid, 0)
                if cid in HOT_CATEGORIES:
                    hot_counts[idx] += qty
                elif cid in COLD_CATEGORIES:
                    cold_counts[idx] += qty
            except Exception:
                continue

    # Накопительные значения
    hot_cumulative, cold_cumulative = [], []
    total_hot, total_cold = 0, 0
    for h, c in zip(hot_counts, cold_counts):
        total_hot += h
        total_cold += c
        hot_cumulative.append(total_hot)
        cold_cumulative.append(total_cold)

    labels = [f"{h:02d}:00" for h in hours]
    return {"labels": labels, "hot": hot_cumulative, "cold": cold_cumulative}


# ======================
# Бронирования
# ======================
def fetch_bookings():
    url = "https://poka-net3.choiceqr.com/api/bookings/list"
    headers = {"Authorization": f"Bearer {CHOICE_TOKEN}"}
    try:
        resp = requests.get(url, headers=headers, timeout=20)
        data = resp.json().get("response", [])
    except Exception as e:
        print("ERROR Choice API:", e, file=sys.stderr, flush=True)
        return []

    bookings = []
    for b in data:
        bookings.append({
            "name": b.get("name", "—"),
            "time": b.get("time", "—"),
            "guests": b.get("persons", "—"),
        })
    return bookings


# ======================
# Flask endpoints
# ======================
@app.route("/api/sales")
def api_sales():
    global cache, last_update
    if time.time() - last_update > 60:
        sales = fetch_category_sales()
        cache["hot"] = sales["hot"]
        cache["cold"] = sales["cold"]
        cache["hourly"] = fetch_hourly()
        cache["bookings"] = fetch_bookings()
        last_update = time.time()
    return jsonify(cache)


@app.route("/")
def index():
    template = """
    <html>
    <head>
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <style>
            body { font-family: Inter, Arial, sans-serif; background: #111; color: #eee; text-align: center; margin: 0; }
            h2 { font-size: 28px; margin: 10px 0; }
            .grid { display: flex; justify-content: center; gap: 20px; margin: 20px; }
            .block { flex: 1; min-width: 300px; padding: 10px; border-radius: 10px; background: #1a1a1a; }
            table { width: 100%; font-size: 18px; border-collapse: collapse; margin-top: 10px; }
            td { padding: 4px 8px; text-align: left; }
            .logo { position: fixed; right: 20px; bottom: 10px; font-size: 20px; font-weight: bold; color: white; font-family: Inter, sans-serif; }
        </style>
    </head>
    <body>
        <div class="grid">
            <div class="block">
                <h2>🔥 Гарячий цех</h2>
                <table id="hot_table"></table>
            </div>
            <div class="block">
                <h2>❄️ Холодний цех</h2>
                <table id="cold_table"></table>
            </div>
            <div class="block">
                <h2>📅 Бронювання</h2>
                <table id="bookings"></table>
            </div>
        </div>
        <div class="block" style="margin:20px;">
            <h2>📊 Замовлення по годинах</h2>
            <canvas id="hourlyChart" height="100"></canvas>
        </div>
        <div class="logo">GRECO</div>

        <script>
        async function updateData() {
            try {
                const res = await fetch('/api/sales');
                const data = await res.json();

                function fillTable(elemId, obj) {
                    let html = "";
                    for (const [k,v] of Object.entries(obj)) {
                        html += `<tr><td>${k}</td><td style="text-align:right;">${v}</td></tr>`;
                    }
                    document.getElementById(elemId).innerHTML = html;
                }
                fillTable("hot_table", data.hot);
                fillTable("cold_table", data.cold);

                let bhtml = "";
                data.bookings.forEach(b => {
                    bhtml += `<tr><td>${b.name}</td><td>${b.time}</td><td>${b.guests} гостей</td></tr>`;
                });
                document.getElementById("bookings").innerHTML = bhtml;

                const ctx = document.getElementById('hourlyChart').getContext('2d');
                if (window.hourlyChart) window.hourlyChart.destroy();
                window.hourlyChart = new Chart(ctx, {
                    type: 'line',
                    data: {
                        labels: data.hourly.labels,
                        datasets: [
                            { label: 'Гарячий цех', data: data.hourly.hot, borderColor: 'orange', fill: false },
                            { label: 'Холодний цех', data: data.hourly.cold, borderColor: 'skyblue', fill: false }
                        ]
                    },
                    options: { responsive: true, plugins: { legend: { labels: { color: 'white' } } }, scales: { x: { ticks: { color: 'white' } }, y: { ticks: { color: 'white' } } } }
                });

            } catch (e) {
                console.error("Ошибка обновления:", e);
            }
        }
        setInterval(updateData, 60000);
        window.onload = updateData;
        </script>
    </body>
    </html>
    """
    return render_template_string(template)


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
