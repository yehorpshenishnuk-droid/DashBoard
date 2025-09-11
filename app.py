import os
import time
import requests
import sys
from datetime import date, datetime
from flask import Flask, render_template_string, jsonify

app = Flask(__name__)

POSTER_TOKEN = os.getenv("POSTER_TOKEN")
CHOICE_TOKEN = os.getenv("CHOICE_TOKEN")  # 🔑 Новый токен для Choice API
ACCOUNT_NAME = "poka-net3"

# ======================
# Словари цехов
# ======================
HOT_DISHES = {  # (оставляем как у тебя)
    14: "Чебурек з моцарелою та сулугуні",
    8: "Чебурек з телятиною",
    # ... и остальные
}

COLD_DISHES = {  # (оставляем как у тебя)
    493: "Пельмені з філе молодої курки, 500 г",
    495: "Пельмені як мають бути з телятиною, 500 г",
    # ... и остальные
}

last_update = 0
cache = {"hot": {}, "cold": {}, "bookings": []}


def fetch_sales(dishes_dict):
    today = date.today().strftime("%Y-%m-%d")
    url = (
        f"https://{ACCOUNT_NAME}.joinposter.com/api/dash.getProductsSales"
        f"?token={POSTER_TOKEN}&date_from={today}&date_to={today}"
    )

    resp = requests.get(url)
    try:
        data = resp.json().get("response", [])
    except Exception as e:
        print("ERROR parsing JSON:", e, file=sys.stderr, flush=True)
        return {"total": 0, "top3": [("Помилка", 0)]}

    sales_count = {}
    total_orders = 0

    for item in data:
        try:
            product_id = int(item.get("product_id", 0))
            quantity = int(float(item.get("count", 0)))
        except Exception:
            continue

        if product_id in dishes_dict:
            sales_count[product_id] = sales_count.get(product_id, 0) + quantity
            total_orders += quantity

    top3 = sorted(sales_count.items(), key=lambda x: x[1], reverse=True)[:3]

    return {"total": total_orders, "top3": [(dishes_dict[i], c) for i, c in top3]}


def fetch_bookings():
    """Получаем список активных броней из Choice API"""
    today = date.today().strftime("%Y-%m-%d")
    url = (
        f"https://open-api.choiceqr.com/bookings/list"
        f"?periodField=bookingDt&from={today}T00:00:00Z&till={today}T23:59:59Z"
    )
    headers = {"Authorization": f"Bearer {CHOICE_TOKEN}"}

    try:
        resp = requests.get(url, headers=headers)
        data = resp.json()
    except Exception as e:
        print("ERROR fetching bookings:", e, file=sys.stderr, flush=True)
        return []

    bookings = []
    for b in data:
        if b.get("status") not in ["cancelled", "expired", "notCame"]:  # фильтруем
            bookings.append(
                {
                    "time": b.get("dateTime"),
                    "persons": b.get("personCount", 0),
                    "name": b.get("customer", {}).get("name", "Гість"),
                }
            )
    return bookings


@app.route("/api/hot")
def api_hot():
    global last_update, cache
    if time.time() - last_update > 30:
        cache["hot"] = fetch_sales(HOT_DISHES)
    return jsonify(cache["hot"])


@app.route("/api/cold")
def api_cold():
    global last_update, cache
    if time.time() - last_update > 30:
        cache["cold"] = fetch_sales(COLD_DISHES)
        last_update = time.time()
    return jsonify(cache["cold"])


@app.route("/api/bookings")
def api_bookings():
    global last_update, cache
    if time.time() - last_update > 30:
        cache["bookings"] = fetch_bookings()
    return jsonify(cache["bookings"])


@app.route("/")
def index():
    template = """
    <html>
    <head>
        <style>
            body { font-family: Arial, sans-serif; background: #111; color: #eee; text-align: center; }
            h2 { font-size: 40px; margin-bottom: 20px; }
            .grid { display: flex; justify-content: center; gap: 50px; max-width: 1400px; margin: auto; }
            .block { width: 650px; padding: 30px; border-radius: 15px; box-shadow: 0 0 20px rgba(0,0,0,0.7); animation: fadeIn 1s; }
            .hot { border: 4px solid #ff6600; }
            .cold { border: 4px solid #0099ff; }
            .item { font-size: 28px; margin: 8px 0; }
            .total { margin-top: 40px; font-size: 34px; font-weight: bold; }
            .bookings { margin-top: 50px; font-size: 28px; }
            .updated { margin-top: 10px; font-size: 18px; color: #aaa; }
            @keyframes fadeIn { from {opacity: 0;} to {opacity: 1;} }
        </style>
    </head>
    <body>
        <div class="grid">
            <div class="block hot">
                <h2>🔥 Гарячий ЦЕХ</h2>
                <p id="hot_total">Всього: ...</p>
                <div id="hot_top3">Загрузка...</div>
            </div>
            <div class="block cold">
                <h2>❄️ Холодний ЦЕХ</h2>
                <p id="cold_total">Всього: ...</p>
                <div id="cold_top3">Загрузка...</div>
            </div>
        </div>
        <div class="total" id="all_total">Загальна кількість замовлень: ...</div>
        <div class="bookings">
            <h2>📅 Бронювання</h2>
            <div id="booking_list">Загрузка...</div>
        </div>
        <div class="updated" id="updated_time">Оновлено: ...</div>

        <script>
        async function updateData() {
            try {
                const hotRes = await fetch('/api/hot');
                const hot = await hotRes.json();
                document.getElementById('hot_total').innerText = "Всього: " + hot.total;
                let hotDiv = document.getElementById('hot_top3');
                hotDiv.innerHTML = "🏆 ТОП-3 продажі:";
                hot.top3.forEach((item, index) => {
                    hotDiv.innerHTML += `<div class="item">${item[0]} — ${item[1]}</div>`;
                });

                const coldRes = await fetch('/api/cold');
                const cold = await coldRes.json();
                document.getElementById('cold_total').innerText = "Всього: " + cold.total;
                let coldDiv = document.getElementById('cold_top3');
                coldDiv.innerHTML = "🏆 ТОП-3 продажі:";
                cold.top3.forEach((item, index) => {
                    coldDiv.innerHTML += `<div class="item">${item[0]} — ${item[1]}</div>`;
                });

                const all = hot.total + cold.total;
                document.getElementById('all_total').innerText = "Загальна кількість замовлень: " + all;

                const bookingRes = await fetch('/api/bookings');
                const bookings = await bookingRes.json();
                let bDiv = document.getElementById('booking_list');
                if (bookings.length === 0) {
                    bDiv.innerHTML = "<i>Немає активних бронювань</i>";
                } else {
                    bDiv.innerHTML = "";
                    bookings.forEach(b => {
                        const time = new Date(b.time).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});
                        bDiv.innerHTML += `<div class="item">🕒 ${time} — ${b.name} (${b.persons} гостей)</div>`;
                    });
                }

                const now = new Date();
                document.getElementById('updated_time').innerText = "Оновлено: " + now.toLocaleTimeString();
            } catch (e) {
                console.error("Ошибка обновления:", e);
            }
        }

        setInterval(updateData, 30000);
        window.onload = updateData;
        </script>
    </body>
    </html>
    """
    return render_template_string(template)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
