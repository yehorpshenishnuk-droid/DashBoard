import os
import time
import requests
import sys
from datetime import date, datetime, timedelta, timezone
try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None
from flask import Flask, render_template_string, jsonify

app = Flask(__name__)

# ======================
# Токены и настройки
# ======================
POSTER_TOKEN = os.getenv("POSTER_TOKEN")
ACCOUNT_NAME = "poka-net3"
CHOICE_TOKEN = os.getenv("CHOICE_TOKEN", "VlFmffA-HWXnYEm-cOXRIze-FDeVdAw")

# ======================
# Категории Poster POS ID -> Группы отображения
# ======================
HOT_CATEGORIES = {
    4:  "Чебуреки/Янтики",
    15: "Чебуреки/Янтики",
    33: "Піде",
    13: "М'ясні страви",
    46: "Гарячі страви",
}

COLD_CATEGORIES = {
    7:  "Манти",
    8:  "Деруни",
    11: "Салати",
    16: "Супи",
    18: "Млинці та сирники",
    19: "Закуски",
    29: "Пісне меню",
    32: "Десерти",
    36: "Сніданки",
    44: "Власне виробництво",
}

cache = {"hot": {}, "cold": {}, "bookings": {}, "hourly": {}}
TTL_SECONDS = 30


# ======================
# Poster API — продажи по категориям
# ======================
def fetch_sales(category_map):
    today = date.today().strftime("%Y%m%d")
    url = (
        f"https://{ACCOUNT_NAME}.joinposter.com/api/dash.getCategoriesSales"
        f"?token={POSTER_TOKEN}&dateFrom={today}&dateTo={today}"
    )
    resp = requests.get(url, timeout=20)
    print("DEBUG Poster API:", resp.text[:300], file=sys.stderr, flush=True)

    try:
        data = resp.json().get("response", [])
    except Exception as e:
        print("ERROR Poster JSON:", e, file=sys.stderr, flush=True)
        return {"total": 0, "items": []}

    counts = {}
    total = 0
    for cat in data:
        cat_id = int(cat.get("category_id", 0))
        qty = int(float(cat.get("count", 0)))
        if cat_id in category_map:
            label = category_map[cat_id]
            counts[label] = counts.get(label, 0) + qty
            total += qty

    items = sorted(counts.items(), key=lambda x: x[1], reverse=True)
    return {"total": total, "items": items}


# ======================
# Poster API — почасовые продажи
# ======================
def fetch_hourly():
    today = date.today().strftime("%Y-%m-%d")
    url = (
        f"https://{ACCOUNT_NAME}.joinposter.com/api/dash.getProductsSales"
        f"?token={POSTER_TOKEN}&date_from={today}&date_to={today}"
    )
    resp = requests.get(url, timeout=20)
    print("DEBUG Hourly Poster API:", resp.text[:200], file=sys.stderr, flush=True)

    try:
        data = resp.json().get("response", [])
    except Exception as e:
        print("ERROR Hourly Poster JSON:", e, file=sys.stderr, flush=True)
        return {"labels": [], "hot": [], "cold": []}

    hours = list(range(8, 24))
    hot_counts = [0] * len(hours)
    cold_counts = [0] * len(hours)

    for item in data:
        try:
            dt_str = item.get("date")  # "2025-09-12 14:23:10"
            cat_id = int(item.get("menu_category_id", 0))
            qty = int(float(item.get("count", 0)))
            dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
            hour = dt.hour
        except Exception:
            continue

        if hour in hours:
            idx = hours.index(hour)
            if cat_id in HOT_CATEGORIES:
                hot_counts[idx] += qty
            elif cat_id in COLD_CATEGORIES:
                cold_counts[idx] += qty

    hot_cumulative = []
    cold_cumulative = []
    total_hot = 0
    total_cold = 0
    for h, c in zip(hot_counts, cold_counts):
        total_hot += h
        total_cold += c
        hot_cumulative.append(total_hot)
        cold_cumulative.append(total_cold)

    labels = [f"{h:02d}:00" for h in hours]
    return {"labels": labels, "hot": hot_cumulative, "cold": cold_cumulative}


# ======================
# Choice API — Бронювання
# ======================
def _today_range_utc():
    try:
        tz = ZoneInfo("Europe/Kyiv") if ZoneInfo else timezone(timedelta(hours=3))
    except Exception:
        tz = timezone(timedelta(hours=3))
    now_local = datetime.now(tz)
    start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    end_local = start_local + timedelta(days=1)
    return start_local, end_local


def fetch_bookings():
    start_local, end_local = _today_range_utc()
    start_iso = start_local.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    end_iso = end_local.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    url = f"https://{ACCOUNT_NAME}.choiceqr.com/api/bookings/list"
    headers = {"Authorization": f"Bearer {CHOICE_TOKEN}"}
    params = {"perPage": 5, "page": 1, "from": start_iso, "till": end_iso, "periodField": "bookingDt"}

    resp = requests.get(url, headers=headers, params=params, timeout=20)
    print("DEBUG Choice API:", resp.status_code, resp.text[:300], file=sys.stderr, flush=True)

    try:
        data = resp.json()
    except Exception as e:
        print("ERROR Choice JSON:", e, file=sys.stderr, flush=True)
        return {"total": 0, "items": []}

    items = None
    for key in ("items", "data", "list", "bookings"):
        v = data.get(key)
        if isinstance(v, list):
            items = v
            break
    if items is None:
        items = []

    total = data.get("totalCount") or data.get("total") or len(items)
    bookings = []
    for b in items:
        customer = b.get("customer") or {}
        name = customer.get("name", "—")
        guests = b.get("personCount") or b.get("guests") or 0
        dt_raw = b.get("dateTime") or b.get("bookingDt") or b.get("startDateTime")
        time_str = dt_raw
        if isinstance(dt_raw, str):
            try:
                dt_parsed = datetime.fromisoformat(dt_raw.replace("Z", "+00:00"))
                tz = ZoneInfo("Europe/Kyiv") if ZoneInfo else timezone(timedelta(hours=3))
                time_str = dt_parsed.astimezone(tz).strftime("%H:%M")
            except Exception:
                pass
        bookings.append({"name": name, "time": time_str, "guests": guests})
    return {"total": int(total) if isinstance(total, (int, float)) else total, "items": bookings}


# ======================
# API endpoints
# ======================
@app.route("/api/hot")
def api_hot():
    if time.time() - cache["hot"].get("ts", 0) > TTL_SECONDS:
        cache["hot"] = fetch_sales(HOT_CATEGORIES)
        cache["hot"]["ts"] = time.time()
    return jsonify(cache["hot"])


@app.route("/api/cold")
def api_cold():
    if time.time() - cache["cold"].get("ts", 0) > TTL_SECONDS:
        cache["cold"] = fetch_sales(COLD_CATEGORIES)
        cache["cold"]["ts"] = time.time()
    return jsonify(cache["cold"])


@app.route("/api/bookings")
def api_bookings():
    cache["bookings"] = fetch_bookings()
    cache["bookings"]["ts"] = time.time()
    return jsonify(cache["bookings"])


@app.route("/api/hourly")
def api_hourly():
    cache["hourly"] = fetch_hourly()
    return jsonify(cache["hourly"])


# ======================
# UI
# ======================
@app.route("/")
def index():
    template = """
    <html>
    <head>
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <style>
            body { font-family: Inter, Arial, sans-serif; background: #111; color: #eee; text-align: center; }
            h2 { font-size: 28px; margin-bottom: 10px; }
            .grid { display: flex; justify-content: center; gap: 20px; max-width: 1600px; margin: auto; flex-wrap: wrap; }
            .block { width: 400px; padding: 15px; border-radius: 10px; box-shadow: 0 0 10px rgba(0,0,0,0.7); }
            .hot { border: 3px solid #ff6600; }
            .cold { border: 3px solid #0099ff; }
            .bookings { border: 3px solid #00ff00; }
            .chart { border: 3px solid #ffaa00; width: 820px; }
            table { width: 100%; border-collapse: collapse; font-size: 16px; }
            td { padding: 4px; text-align: left; }
            td:last-child { text-align: right; }
            .logo { position: fixed; bottom: 10px; right: 20px; font-family: Inter, Arial, sans-serif; font-weight: bold; font-size: 24px; color: white; }
        </style>
    </head>
    <body>
        <div class="grid">
            <div class="block hot">
                <h2>🔥 Гарячий ЦЕХ</h2>
                <p id="hot_total">Всього: ...</p>
                <table id="hot_items"></table>
            </div>
            <div class="block cold">
                <h2>❄️ Холодний ЦЕХ</h2>
                <p id="cold_total">Всього: ...</p>
                <table id="cold_items"></table>
            </div>
            <div class="block bookings">
                <h2>📖 Бронювання</h2>
                <p id="bookings_total">Загальна кількість: ...</p>
                <table id="bookings_list"></table>
            </div>
            <div class="block chart">
                <h2>📊 Діаграма</h2>
                <canvas id="ordersChart" width="800" height="400"></canvas>
            </div>
        </div>
        <div class="logo">GRECO</div>

        <script>
        async function updateData() {
            const hotRes = await fetch('/api/hot'); const hot = await hotRes.json();
            document.getElementById('hot_total').innerText = "Всього: " + hot.total;
            let hotTable = document.getElementById('hot_items'); hotTable.innerHTML = "";
            hot.items.forEach(item => { hotTable.innerHTML += `<tr><td>${item[0]}</td><td>${item[1]}</td></tr>`; });

            const coldRes = await fetch('/api/cold'); const cold = await coldRes.json();
            document.getElementById('cold_total').innerText = "Всього: " + cold.total;
            let coldTable = document.getElementById('cold_items'); coldTable.innerHTML = "";
            cold.items.forEach(item => { coldTable.innerHTML += `<tr><td>${item[0]}</td><td>${item[1]}</td></tr>`; });

            const bookRes = await fetch('/api/bookings'); const bookings = await bookRes.json();
            document.getElementById('bookings_total').innerText = "Загальна кількість: " + bookings.total;
            let bookTable = document.getElementById('bookings_list'); bookTable.innerHTML = "";
            bookings.items.forEach(b => { bookTable.innerHTML += `<tr><td>${b.name} (${b.time})</td><td>${b.guests}</td></tr>`; });

            const hourRes = await fetch('/api/hourly'); const hourly = await hourRes.json();
            const ctx = document.getElementById('ordersChart').getContext('2d');
            new Chart(ctx, {
                type: 'line',
                data: {
                    labels: hourly.labels,
                    datasets: [
                        { label: 'Гарячий цех', data: hourly.hot, borderColor: 'orange', fill: false },
                        { label: 'Холодний цех', data: hourly.cold, borderColor: 'skyblue', fill: false }
                    ]
                },
                options: {
                    responsive: false,
                    plugins: { legend: { labels: { color: 'white' } } },
                    scales: {
                        x: { ticks: { color: 'white' } },
                        y: { beginAtZero: true, ticks: { color: 'white' } }
                    }
                }
            });
        }
        updateData();
        setInterval(updateData, 60000);
        </script>
    </body>
    </html>
    """
    return render_template_string(template)


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
