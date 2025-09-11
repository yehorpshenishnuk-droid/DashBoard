import os
import sys
import time
import requests
from flask import Flask, jsonify, render_template_string
from datetime import datetime, date

app = Flask(__name__)

# Poster API токен и аккаунт
POSTER_TOKEN = os.getenv("POSTER_TOKEN", "")
ACCOUNT_NAME = os.getenv("POSTER_ACCOUNT", "poka-net3")

# Горячий цех
HOT_DISHES = {
    12: "Чебурек з свининою",
    13: "Чебурек з куркою",
    14: "Чебурек з моцарелою та сулугуні",
    243: "Чебурек з томатами та грибами",
    327: "Чебурек з вишнею та вершковим крем сиром",
    347: "Чебурек з баранниною",
    515: "Телячі щічки з картопляним пюре",
    154: "Плов який Ви полюбите",
    210: "Піде з телятиною",
    209: "Піде з куркою та томатами",
    545: "Піде з моцарелою, томатами та песто",
    360: "Сирне піде з інжиром та фісташкою",
    208: "Піде з сиром та часниковим соусом",
}

# Холодный цех
COLD_DISHES = {
    493: "Пельмені з філе молодої курки",
    495: "Пельмені як мають бути з телятиною",
    510: "Пельмені свино-яловичі",
    399: "Салат з запеченими овочами",
    487: "Салат з хамоном та грушею",
    55: "Салат цезарь",
    40: "Грецький салат",
    288: "Крем-суп гарбузовий з беконом",
    262: "Крем-суп грибний з грінками",
    42: "М'ясна солянка",
    206: "Окрошка на айрані з ковбасою",
    44: "Манти з яловичиною",
    521: "Пельмені з філе курки",
    429: "Манти з сиром та зеленью",
    49: "Деруни зі сметаною",
    68: "Картопля Фрі з соусами",
    67: "Сирна тарілка",
    69: "Сирні хрусткі палички",
    63: "Млинці солодкі з сиром",
    47: "Сирники",
    57: "Сирні кульки",
    214: "Шоколадний фондан",
    331: "Чизкейк LA",
    401: "Ніжне крем-брюле",
}

# Кэш
last_update = {"hot": 0, "cold": 0, "timeline": 0}
cache = {
    "hot": {"total": 0, "top3": []},
    "cold": {"total": 0, "top3": []},
    "timeline": {"labels": [], "values": []},
}


def fetch_sales(dishes_dict):
    """Запрос продаж по списку блюд"""
    today = date.today().strftime("%Y-%m-%d")
    url = f"https://{ACCOUNT_NAME}.joinposter.com/api/dash.getProductsSales"
    params = {"token": POSTER_TOKEN, "date_from": today, "date_to": today}
    try:
        resp = requests.get(url, params=params)
        data = resp.json().get("response", [])
    except Exception as e:
        print("ERROR fetch_sales:", e, file=sys.stderr, flush=True)
        return {"total": 0, "top3": []}

    total = 0
    sales = []
    for item in data:
        pid = int(item.get("product_id", 0))
        if pid in dishes_dict:
            count = float(item.get("count", 0))
            sales.append((dishes_dict[pid], int(count)))
            total += int(count)

    sales.sort(key=lambda x: x[1], reverse=True)
    return {"total": total, "top3": sales[:3]}


def fetch_timeline():
    """Все заказы по часам (9:00–23:00)"""
    today = date.today().strftime("%Y-%m-%d")
    url = f"https://{ACCOUNT_NAME}.joinposter.com/api/dash.getTransactions"
    params = {"token": POSTER_TOKEN, "date_from": today, "date_to": today}
    try:
        resp = requests.get(url, params=params)
        data = resp.json().get("response", [])
        print("DEBUG transactions sample:", data[:3], file=sys.stderr, flush=True)
    except Exception as e:
        print("ERROR fetch_timeline:", e, file=sys.stderr, flush=True)
        return {"labels": [], "values": []}

    timeline = {}
    for item in data:
        try:
            ts = int(item.get("date_start", 0))
            dt = datetime.fromtimestamp(ts)
            hour = dt.hour
            if 9 <= hour <= 23:
                timeline[hour] = timeline.get(hour, 0) + 1
        except Exception as e:
            print("ERROR parse transaction:", e, file=sys.stderr, flush=True)
            continue

    labels = [f"{h:02d}:00" for h in range(9, 24)]
    values = [timeline.get(h, 0) for h in range(9, 24)]
    return {"labels": labels, "values": values}


@app.route("/api/hot")
def api_hot():
    if time.time() - last_update["hot"] > 30:
        cache["hot"] = fetch_sales(HOT_DISHES)
        last_update["hot"] = time.time()
    return jsonify(cache["hot"])


@app.route("/api/cold")
def api_cold():
    if time.time() - last_update["cold"] > 30:
        cache["cold"] = fetch_sales(COLD_DISHES)
        last_update["cold"] = time.time()
    return jsonify(cache["cold"])


@app.route("/api/timeline")
def api_timeline():
    if time.time() - last_update["timeline"] > 30:
        cache["timeline"] = fetch_timeline()
        last_update["timeline"] = time.time()
    return jsonify(cache["timeline"])


@app.route("/")
def index():
    return render_template_string(
        """
        <html>
        <head>
          <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        </head>
        <body style="background:#111; color:white; font-family:Arial;">
          <h2>Графік замовлень за день</h2>
          <canvas id="timelineChart" width="900" height="400"></canvas>
          <script>
            async function loadTimeline() {
              let r = await fetch('/api/timeline');
              let data = await r.json();
              let ctx = document.getElementById('timelineChart').getContext('2d');
              new Chart(ctx, {
                type: 'bar',
                data: {
                  labels: data.labels,
                  datasets: [{
                    label: 'Замовлення за день',
                    data: data.values,
                    backgroundColor: 'rgba(0,200,83,0.7)'
                  }]
                }
              });
            }
            loadTimeline();
          </script>
        </body>
        </html>
        """
    )


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
