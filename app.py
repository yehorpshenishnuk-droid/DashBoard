import os
import time
import requests
import sys
from datetime import date, datetime, timedelta, timezone
try:
    from zoneinfo import ZoneInfo  # Python 3.9+
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
    4:  "Чебуреки/Янтики",   # ЧЕБУРЕКИ
    15: "Чебуреки/Янтики",   # ЯНТИКИ
    33: "Піде",              # ПИДЕ
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

cache = {"hot": {}, "cold": {}, "bookings": {}}
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

    # теперь берём все категории, не только топ-3
    items = sorted(counts.items(), key=lambda x: x[1], reverse=True)
    return {"total": total, "items": items}


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

    start_utc = start_local.astimezone(timezone.utc)
    end_utc = end_local.astimezone(timezone.utc)

    return start_utc.isoformat().replace("+00:00", "Z"), end_utc.isoformat().replace("+00:00", "Z")


def fetch_bookings():
    start_iso, end_iso = _today_range_utc()
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
            h2 { font-size: 36px; margin-bottom: 15px; }
            .grid { display: flex; justify-content: center; gap: 40px; max-width: 1600px; margin: auto; flex-wrap: wrap; }
            .block { width: 450px; padding: 25px; border-radius: 15px; box-shadow: 0 0 20px rgba(0,0,0,0.7); animation: fadeIn 1s; }
            .hot { border: 4px solid #ff6600; }
            .cold { border: 4px solid #0099ff; }
            .bookings { border: 4px solid #00ff00; }
            .item { font-size: 22px; margin: 6px 0; }
            .total { margin-top: 15px; font-size: 26px; font-weight: bold; }
            .updated { margin-top: 10px; font-size: 14px; color: #aaa; }
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
