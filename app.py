import os
import time
import requests
import sys
from datetime import date
from flask import Flask, render_template_string, jsonify

app = Flask(__name__)

POSTER_TOKEN = os.getenv("POSTER_TOKEN")
ACCOUNT_NAME = "poka-net3"  # твой поддомен Poster

# Список горячего цеха (id: название)
HOT_DISHES = {
    14: "Чебурек з моцарелою та сулугуні",
    8: "Чебурек з телятиною",
    243: "Чебурек з томатами та грибами",
    327: "Чебурек з вишнею та вершковим крем сиром",
    347: "Чебурек з бараниною",
    12: "Чебурек з свининою",
    13: "Чебурек з куркою",
    515: "Телячі щічки з картопляним пюре, 330 г",
    244: "Янтик з томатами та грибами",
    502: "Янтик з фермерським сиром і зеленню",
    349: "Янтик з бараниною",
    74: "Янтик з свининою",
    73: "Янтик з куркою",
    75: "Янтик з моцарелою та сулугуні",
    76: "Янтик з телятиною",
    375: "Янтик з телятиною та сиром чедер",
    154: "Плов який Ви полюбите",
    210: "Піде з телятиною",
    545: "Піде з моцарелою, томатами та песто",
    290: "Люля-кебаб з трьома видами м'яса",
    528: "Ніжне куряче стегно гриль, 360 г",
    296: "М'ясний сет 1,770",
    325: "Люля-кебаб з сиром та трьома видами м'яса",
    295: "Реберця в медово-гірчичному соусі",
    222: "Телятина на грилі",
    72: "Філе молодої курки",
    71: "Шийна частина свинини",
    209: "Піде з куркою та томатами",
    360: "Сирне піде з інжиром та фісташкою",
    208: "Піде з сиром та часниковим соусом",
}

last_update = 0
hot_data = {}


def fetch_sales():
    """Получаем продажи из Poster API за текущий день"""
    today = date.today().strftime("%Y-%m-%d")
    url = (
        f"https://{ACCOUNT_NAME}.joinposter.com/api/dash.getProductsSales"
        f"?token={POSTER_TOKEN}&date_from={today}&date_to={today}"
    )

    resp = requests.get(url)
    print("DEBUG Poster API response:", resp.text[:300], file=sys.stderr, flush=True)

    try:
        data = resp.json().get("response", [])
    except Exception as e:
        print("ERROR parsing JSON:", e, file=sys.stderr, flush=True)
        return {"total": 0, "top3": [("Ошибка", 0)]}

    sales_count = {}
    total_orders = 0

    for item in data:
        try:
            product_id = int(item.get("product_id", 0))
            quantity = int(float(item.get("count", 0)))
        except Exception:
            continue

        if product_id in HOT_DISHES:
            sales_count[product_id] = sales_count.get(product_id, 0) + quantity
            total_orders += quantity

    top3 = sorted(sales_count.items(), key=lambda x: x[1], reverse=True)[:3]

    return {
        "total": total_orders,
        "top3": [(HOT_DISHES[i], c) for i, c in top3]
    }


@app.route("/api/hot")
def api_hot():
    """API для фронтенда (JSON)"""
    global last_update, hot_data
    if time.time() - last_update > 30:
        try:
            hot_data = fetch_sales()
            last_update = time.time()
        except Exception as e:
            hot_data = {"total": 0, "top3": [("Ошибка", 0)]}
            print("ERROR fetch_sales:", e, file=sys.stderr, flush=True)
    return jsonify(hot_data)


@app.route("/")
def index():
    """Главная страница"""
    template = """
    <html>
    <head>
        <style>
            body { font-family: Arial, sans-serif; background: #111; color: #eee; text-align: center; }
            h2 { color: orange; }
            .block { margin: 30px auto; width: 420px; padding: 20px; border: 2px solid orange; border-radius: 10px; }
            .item { font-size: 20px; margin: 5px 0; }
        </style>
    </head>
    <body>
        <div class="block">
            <h2>🔥 Гарячий ЦЕХ</h2>
            <p id="total">Всього: ... замовлень</p>
            <div id="top3">Загрузка...</div>
        </div>

        <script>
        async function updateData() {
            try {
                const res = await fetch('/api/hot');
                const data = await res.json();

                document.getElementById('total').innerText = "Всього: " + data.total + " замовлень";

                let topDiv = document.getElementById('top3');
                topDiv.innerHTML = "🏆 ТОП-3 продажі:";
                data.top3.forEach((item, index) => {
                    topDiv.innerHTML += `<div class="item">${index+1}) ${item[0]} — ${item[1]}</div>`;
                });
            } catch (e) {
                console.error("Ошибка обновления:", e);
            }
        }

        setInterval(updateData, 30000); // обновлять каждые 30 секунд
        window.onload = updateData;
        </script>
    </body>
    </html>
    """
    return render_template_string(template)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
