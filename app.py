import os
import time
import requests
import sys
from flask import Flask, render_template_string

app = Flask(__name__)

POSTER_TOKEN = os.getenv("POSTER_TOKEN")
ACCOUNT_NAME = "poka-net3"  # твой поддомен Poster

# Список горячего цеха (id: название)
HOT_DISHES = {
    14: "Чебурек з моцарелою та сулугуні",
    8: "Чебурек з телятиною",
    243: "Чебурек з томатами та грибами",
    327: "Чебурек з вишнею та вершковим крем сиром",
    347: "Чебурек з баранниною",
    12: "Чебурек з свининою",
    13: "Чебурек з куркою",
    515: "Телячі щічки з картопляним пюре, 330 г",
    244: "Янтик з томатами та грибами",
    502: "Янтик з фермерським сиром і зеленью",
    349: "Янтик з бараниною",
    74: "Янтик з свининою",
    73: "Янтик з куркою",
    75: "Янтик з моцарелою та сулугуні",
    76: "Янтик з телятиною",
    375: "Янтик з телятиною та сиром чедер",
    154: "Плов який Ви полюбите",
    210: "Піде з телятиною",
    545: "Піде з моцарелою , томатами та песто",
    290: "Люля-кебаб з трьома видами м'яса",
    528: "Ніжне куряче стегно гриль, 360",
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
    """Получаем продажи из Poster API"""
    url = f"https://{ACCOUNT_NAME}.joinposter.com/api/dash.getProductsSales?token={POSTER_TOKEN}"
    resp = requests.get(url)

    print("DEBUG Poster API response:", resp.text[:500], file=sys.stderr, flush=True)

    try:
        data = resp.json().get("response", [])
    except Exception as e:
        print("ERROR parsing JSON:", e, file=sys.stderr, flush=True)
        return {"total": 0, "top3": [("Ошибка", 0)]}

    sales_count = {}
    total_checks = 0

    for item in data:
        try:
            product_id = int(item.get("product_id", 0))
            quantity = int(float(item.get("count", 0)))
        except Exception:
            continue

        if product_id in HOT_DISHES:
            sales_count[product_id] = sales_count.get(product_id, 0) + quantity
            total_checks += quantity

    top3 = sorted(sales_count.items(), key=lambda x: x[1], reverse=True)[:3]

    return {
        "total": total_checks,
        "top3": [(HOT_DISHES[i], c) for i, c in top3]
    }


@app.route("/")
def index():
    global last_update, hot_data
    if time.time() - last_update > 30:
        try:
            hot_data = fetch_sales()
            last_update = time.time()
        except Exception as e:
            hot_data = {"total": 0, "top3": [("Ошибка", 0)]}
            print("ERROR fetch_sales:", e, file=sys.stderr, flush=True)

    template = """
    <html>
    <head>
        <meta http-equiv="refresh" content="30">
        <style>
            body { font-family: Arial, sans-serif; background: #111; color: #eee; text-align: center; }
            h2 { color: orange; }
            .block { margin: 30px auto; width: 400px; padding: 20px; border: 2px solid orange; border-radius: 10px; }
            .item { font-size: 20px; margin: 5px 0; }
        </style>
    </head>
    <body>
        <div class="block">
            <h2>🔥 Горячий ЦЕХ</h2>
            <p>{{ hot.total }} чеков</p>
            {% for name, count in hot.top3 %}
                <div class="item">{{ loop.index }}) {{ name }} — {{ count }}</div>
            {% endfor %}
        </div>
    </body>
    </html>
    """
    return render_template_string(template, hot=hot_data)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
