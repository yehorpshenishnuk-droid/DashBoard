import os
import time
import requests
import sys
from datetime import date, datetime
from flask import Flask, render_template_string, jsonify

app = Flask(__name__)

POSTER_TOKEN = os.getenv("POSTER_TOKEN")
ACCOUNT_NAME = "poka-net3"

# Категории для подсчета
HOT_CATEGORIES = {4, 13, 15, 46, 33}  # ЧЕБУРЕКИ, МЯСНІ СТРАВИ, ЯНТИКИ, ГОРЯЧІ СТРАВИ, ПИДЕ
COLD_CATEGORIES = {7, 8, 11, 16, 18, 19, 29, 32, 36, 44}  # Манты, Деруни, Салаты, Супы и т.д.

CHOICE_TOKEN = os.getenv("CHOICE_TOKEN")

last_update = 0
cache = {"hot": {}, "cold": {}, "bookings": {}, "hourly": {}}


def fetch_sales():
    """Получаем продажи по категориям за текущий день"""
    today = date.today().strftime("%Y%m%d")
    url = (
        f"https://{ACCOUNT_NAME}.joinposter.com/api/dash.getCategoriesSales"
        f"?token={POSTER_TOKEN}&dateFrom={today}&dateTo={today}"
    )
    resp = requests.get(url, timeout=20)
    print("DEBUG Poster API:", resp.text[:200], file=sys.stderr, flush=True)

    try:
        data = resp.json().get("response", [])
    except Exception as e:
        print("ERROR parsing JSON:", e, file=sys.stderr, flush=True)
        return {"hot": {}, "cold": {}}

    hot_sales = {}
    cold_sales = {}

    for item in data:
        try:
            cat_id = int(item.get("category_id", 0))
            name = item.get("category_name", "").strip()
            count = int(float(item.get("count", 0)))
        except Exception:
            continue

        if cat_id in HOT_CATEGORIES:
            hot_sales[name] = hot_sales.get(name, 0) + count
        elif cat_id in COLD_CATEGORIES:
            cold_sales[name] = cold_sales.get(name, 0) + count

    return {"hot": hot_sales, "cold": cold_sales}


def fetch_hourly():
    """Получаем почасовые продажи для диаграммы"""
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
            dt_str = item.get("date_close") or item.get("modified") or item.get("date")
            cat_id = int(item.get("category_id", 0))
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

    hot_cumulative, cold_cumulative = [], []
    total_hot, total_cold = 0, 0
    for h, c in zip(hot_counts, cold_counts):
        total_hot += h
        total_cold += c
        hot_cumulative.append(total_hot)
        cold_cumulative.append(total_cold)

    labels = [f"{h:02d}:00" for h in hours]
    return {"labels": labels, "hot": hot_cumulative, "cold": cold_cumulative}


def fetch_bookings():
    """Получаем количество броней из Choice"""
    url = "https://poka-net3.choiceqr.com/api/bookings/list"
    headers = {"Authorization": f"Bearer {CHOICE_TOKEN}"}
    try:
        resp = requests.get(url, headers=headers, timeout=20)
        print("DEBUG Choice API:", resp.text[:200], file=sys.stderr, flush=True)
        data = resp.json().get("response", [])
        total = len(data)
        return {"total": total, "bookings": data[:5]}  # ограничим 5 последних
    except Exception as e:
        print("ERROR Choice API:", e, file=sys.stderr, flush=True)
        return {"total": 0, "bookings": []}


@app.route("/api/sales")
def api_sales():
    global last_update, cache
    if time.time() - last_update > 60:
        res = fetch_sales()
        cache["hot"] = res["hot"]
        cache["cold"] = res["cold"]
        cache["hourly"] = fetch_hourly()
        cache["bookings"] = fetch_bookings()
        last_update = time.time()
    return jsonify({"hot": cache["hot"], "cold": cache["cold"], "hourly": cache["hourly"], "bookings": cache["bookings"]})


@app.route("/")
def index():
    template = """
    <html>
    <head>
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <style>
            body { font-family: Inter, Arial, sans-serif; background: #111; color: #eee; text-align: center; margin: 0; }
            h2 { font-size: 28px; margin: 10px 0; }
            .grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 20px; padding: 20px; }
            .block { padding: 15px; border-radius: 12px; box-shadow: 0 0 15px rgba(0,0,0,0.6); }
            .hot { border: 3px solid #ff6600; }
            .cold { border: 3px solid #0099ff; }
            .bookings { border: 3px solid #00cc44; }
            .chart { border: 3px solid orange; grid-column: span 3; }
            table { width: 100%; border-collapse: collapse; }
            td { padding: 6px 10px; font-size: 18px; text-align: left; }
            .logo { position: fixed; bottom: 10px; right: 20px; font-size: 24px; font-weight: bold; color: white; font-family: Inter, Arial, sans-serif; }
        </style>
    </head>
    <body>
        <div class="grid">
            <div class="block hot">
                <h2>🔥 Гарячий Цех</h2>
                <table id="hot_table"></table>
            </div>
            <div class="block cold">
                <h2>❄️ Холодний Цех</h2>
                <table id="cold_table"></table>
            </div>
            <div class="block bookings">
                <h2>📖 Бронювання</h2>
                <p id="bookings_total" style="font-size:22px; font-weight:bold;"></p>
                <div id="bookings_list"></div>
            </div>
            <div class="block chart">
                <h2>📊 Діаграма</h2>
                <canvas id="salesChart" height="120"></canvas>
            </div>
        </div>
        <div class="logo">GRECO</div>

        <script>
        async function updateData() {
            try {
                const res = await fetch('/api/sales');
                const data = await res.json();

                let hotHTML = "";
                for (let [name, count] of Object.entries(data.hot)) {
                    hotHTML += `<tr><td>${name}</td><td style="text-align:right;">${count}</td></tr>`;
                }
                document.getElementById('hot_table').innerHTML = hotHTML;

                let coldHTML = "";
                for (let [name, count] of Object.entries(data.cold)) {
                    coldHTML += `<tr><td>${name}</td><td style="text-align:right;">${count}</td></tr>`;
                }
                document.getElementById('cold_table').innerHTML = coldHTML;

                document.getElementById('bookings_total').innerText = "Загальна кількість: " + data.bookings.total;
                let blist = "";
                data.bookings.bookings.forEach(b => {
                    blist += `<div>${b.customer?.name || "Клієнт"} — ${b.personCount} гостей о ${b.dateTime}</div>`;
                });
                document.getElementById('bookings_list').innerHTML = blist;

                const ctx = document.getElementById('salesChart').getContext('2d');
                if (window.salesChart) window.salesChart.destroy();
                window.salesChart = new Chart(ctx, {
                    type: 'line',
                    data: {
                        labels: data.hourly.labels,
                        datasets: [
                            { label: 'Гарячий цех', data: data.hourly.hot, borderColor: 'orange', backgroundColor: 'orange', fill: false },
                            { label: 'Холодний цех', data: data.hourly.cold, borderColor: 'skyblue', backgroundColor: 'skyblue', fill: false }
                        ]
                    },
                    options: { responsive: true, plugins: { legend: { labels: { color: '#fff' } } }, scales: { x: { ticks: { color: '#fff' } }, y: { ticks: { color: '#fff' } } } }
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
