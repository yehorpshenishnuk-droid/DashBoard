import os
import time
import requests
import sys
from datetime import date, datetime
from flask import Flask, render_template_string, jsonify

app = Flask(__name__)

# ======================
# Токены и настройки
# ======================
POSTER_TOKEN = os.getenv("POSTER_TOKEN")
ACCOUNT_NAME = "poka-net3"
CHOICE_TOKEN = os.getenv("CHOICE_TOKEN", "VlFmffA-HWXnYEm-cOXRIze-FDeVdAw")

# ======================
# Категории Poster POS ID
# ======================

HOT_CATEGORIES = {
    4: "Чебуреки/Янтики",
    13: "М'ясні страви",
    15: "Чебуреки/Янтики",
    46: "Гарячі страви",
    33: "Піде",
}

COLD_CATEGORIES = {
    7: "Манти",
    8: "Деруни",
    11: "Салати",
    16: "Супи",
    18: "Млинці та сирники",
    19: "Закуски",
    29: "Пісне меню",
    32: "Десерти",
    36: "Сніданки",
    44: "Власне виробництво",
}

last_update = 0
cache = {"hot": {}, "cold": {}, "bookings": {}, "categories": {}}


# ======================
# Poster API
# ======================
def fetch_sales(group_mode=True):
    """Получаем продажи из Poster API за текущий день"""
    today = date.today().strftime("%Y-%m-%d")
    url = (
        f"https://{ACCOUNT_NAME}.joinposter.com/api/dash.getProductsSales"
        f"?token={POSTER_TOKEN}&date_from={today}&date_to={today}"
    )

    resp = requests.get(url)
    print("DEBUG Poster API response:", resp.text[:500], file=sys.stderr, flush=True)

    try:
        data = resp.json().get("response", [])
    except Exception as e:
        print("ERROR parsing JSON:", e, file=sys.stderr, flush=True)
        return {"total": 0, "items": []}

    sales_count = {}
    total_orders = 0

    for item in data:
        quantity = int(float(item.get("count", 0)))
        cat_id = item.get("menu_category_id")

        try:
            cat_id = int(cat_id)
        except:
            continue

        if group_mode and cat_id in HOT_CATEGORIES:
            key = HOT_CATEGORIES[cat_id]
            sales_count[key] = sales_count.get(key, 0) + quantity
            total_orders += quantity
        elif not group_mode and cat_id in COLD_CATEGORIES:
            key = COLD_CATEGORIES[cat_id]
            sales_count[key] = sales_count.get(key, 0) + quantity
            total_orders += quantity

    top3 = sorted(sales_count.items(), key=lambda x: x[1], reverse=True)[:3]
    return {"total": total_orders, "items": top3}


def fetch_categories():
    """Получаем список категорий из Poster API"""
    url = f"https://{ACCOUNT_NAME}.joinposter.com/api/menu.getCategories?token={POSTER_TOKEN}"
    resp = requests.get(url)
    print("DEBUG menu.getCategories:", resp.text[:500], file=sys.stderr, flush=True)

    try:
        data = resp.json().get("response", [])
    except Exception as e:
        print("ERROR menu.getCategories:", e, file=sys.stderr, flush=True)
        return []

    return [{"id": int(c["category_id"]), "name": c["category_name"]} for c in data]


# ======================
# Choice API (бронювання)
# ======================
def fetch_bookings():
    """Получаем список броней из Choice API"""
    url = f"https://{ACCOUNT_NAME}.choiceqr.com/api/bookings/list"
    headers = {"Authorization": f"Bearer {CHOICE_TOKEN}"}
    params = {"perPage": 5, "page": 1}

    resp = requests.get(url, headers=headers, params=params)
    print("DEBUG bookings response:", resp.text[:300], file=sys.stderr, flush=True)

    try:
        data = resp.json()
    except Exception as e:
        print("ERROR Choice API:", e, file=sys.stderr, flush=True)
        return {"total": 0, "items": []}

    bookings = []
    for b in data.get("data", []):
        customer = b.get("customer", {})
        name = customer.get("name", "—")
        guests = b.get("personCount", 0)
        dt = b.get("dateTime")
        try:
            time_str = datetime.fromisoformat(dt.replace("Z", "+00:00")).strftime("%H:%M")
        except Exception:
            time_str = dt
        bookings.append({"name": name, "time": time_str, "guests": guests})

    total = data.get("totalCount", len(bookings))
    return {"total": total, "items": bookings}


# ======================
# API endpoints
# ======================
@app.route("/api/hot")
def api_hot():
    global last_update, cache
    if time.time() - last_update > 30:
        cache["hot"] = fetch_sales(group_mode=True)
    return jsonify(cache["hot"])


@app.route("/api/cold")
def api_cold():
    global last_update, cache
    if time.time() - last_update > 30:
        cache["cold"] = fetch_sales(group_mode=False)
        last_update = time.time()
    return jsonify(cache["cold"])


@app.route("/api/bookings")
def api_bookings():
    cache["bookings"] = fetch_bookings()
    return jsonify(cache["bookings"])


@app.route("/api/categories")
def api_categories():
    cache["categories"] = fetch_categories()
    return jsonify(cache["categories"])


# ======================
# UI
# ======================
@app.route("/")
def index():
    template = """
    <html>
    <head>
        <style>
            body { font-family: Arial, sans-serif; background: #111; color: #eee; text-align: center; }
            h2 { font-size: 40px; margin-bottom: 20px; }
            .grid { display: flex; justify-content: center; gap: 50px; max-width: 1600px; margin: auto; flex-wrap: wrap; }
            .block { width: 450px; padding: 30px; border-radius: 15px; box-shadow: 0 0 20px rgba(0,0,0,0.7); animation: fadeIn 1s; }
            .hot { border: 4px solid #ff6600; }
            .cold { border: 4px solid #0099ff; }
            .bookings { border: 4px solid #00ff00; }
            .item { font-size: 24px; margin: 8px 0; }
            .total { margin-top: 20px; font-size: 28px; font-weight: bold; }
            .updated { margin-top: 10px; font-size: 16px; color: #aaa; }
            @keyframes fadeIn { from {opacity: 0;} to {opacity: 1;} }
        </style>
    </head>
    <body>
        <div class="grid">
            <div class="block hot">
                <h2>🔥 Гарячий ЦЕХ</h2>
                <p id="hot_total">Всього: ...</p>
                <div id="hot_items">Загрузка...</div>
            </div>
            <div class="block cold">
                <h2>❄️ Холодний ЦЕХ</h2>
                <p id="cold_total">Всього: ...</p>
                <div id="cold_items">Загрузка...</div>
            </div>
            <div class="block bookings">
                <h2>📖 Бронювання</h2>
                <p id="bookings_total">Загальна кількість: ...</p>
                <div id="bookings_list">Загрузка...</div>
            </div>
        </div>
        <div class="updated" id="updated_time">Оновлено: ...</div>

        <script>
        async function updateData() {
            try {
                const hotRes = await fetch('/api/hot');
                const hot = await hotRes.json();
                document.getElementById('hot_total').innerText = "Всього: " + hot.total + " замовлень";
                let hotDiv = document.getElementById('hot_items');
                hotDiv.innerHTML = "";
                hot.items.forEach((item, index) => {
                    hotDiv.innerHTML += `<div class="item">${index+1}) ${item[0]} — ${item[1]}</div>`;
                });

                const coldRes = await fetch('/api/cold');
                const cold = await coldRes.json();
                document.getElementById('cold_total').innerText = "Всього: " + cold.total + " замовлень";
                let coldDiv = document.getElementById('cold_items');
                coldDiv.innerHTML = "";
                cold.items.forEach((item, index) => {
                    coldDiv.innerHTML += `<div class="item">${index+1}) ${item[0]} — ${item[1]}</div>`;
                });

                const bookRes = await fetch('/api/bookings');
                const bookings = await bookRes.json();
                document.getElementById('bookings_total').innerText = "Загальна кількість: " + bookings.total;
                let bookDiv = document.getElementById('bookings_list');
                bookDiv.innerHTML = "";
                if (bookings.items.length === 0) {
                    bookDiv.innerHTML = "<div class='item'>Немає бронювань</div>";
                } else {
                    bookings.items.forEach((b, index) => {
                        bookDiv.innerHTML += `<div class="item">${index+1}) ${b.name} — ${b.time}, гостей: ${b.guests}</div>`;
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
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
