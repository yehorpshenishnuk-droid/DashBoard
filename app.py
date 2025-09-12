import os
import time
import requests
import sys
from datetime import date
from flask import Flask, render_template_string, jsonify

app = Flask(__name__)

POSTER_TOKEN = os.getenv("POSTER_TOKEN")
ACCOUNT_NAME = "poka-net3"

# ======================
# Группы Чебуреків
# ======================
CHEBUREK_GROUPS = {
    "Чебуреки": [
        "Чебурек з моцарелою та сулугуні",
        "Чебурек з телятиною",
        "Чебурек з томатами та грибами",
        "Чебурек з вишнею та вершковим крем сиром",
        "Чебурек з баранниною",
        "Чебурек з свининою",
        "Чебурек з куркою",
    ]
}

# ======================
# Группы Янтиків
# ======================
YANTYK_GROUPS = {
    "Янтики": [
        "Янтик з томатами та грибами",
        "Янтик з фермерським сиром і зеленью",
        "Янтик з бараниною",
        "Янтик з свининою",
        "Янтик з куркою",
        "Янтик з моцарелою та сулугуні",
        "Янтик з телятиною",
        "Янтик з телятиною та сиром чедер",
    ]
}

# ======================
# Піде (группируем все виды)
# ======================
PIDE_GROUP = {
    "Піде": [
        "Піде з телятиною",
        "Піде з моцарелою , томатами та песто",
        "Піде з куркою та томатами",
        "Сирне піде з інжиром та фісташкою",
        "Піде з сиром та часниковим соусом",
        "Піде з бараниною",
    ]
}

# ======================
# Горячий цех (остальные блюда по ID)
# ======================
HOT_DISHES = {
    515: "Телячі щічки з картопляним пюре, 330 г",
    290: "Люля-кебаб з трьома видами м'яса",
    528: "Ніжне куряче стегно гриль, 360",
    296: "М'ясний сет 1,770",
    325: "Люля-кебаб з сиром та трьома видами м'яса",
    295: "Реберця в медово-гірчичному соусі",
    222: "Телятина на грилі",
    72:  "Філе молодої курки",
    71:  "Шийна частина свинини",
    154: "Плов який Ви полюбите",
}

# ======================
# Холодний цех (по ID)
# ======================
COLD_DISHES = {
    493: "Пельмені з філе молодої курки, 500 г",
    495: "Пельмені як мають бути з телятиною, 500 г",
    510: "Пельмені свино-яловичі , 500г",
    399: "Салат з запеченими овочами",
    487: "Салат з хамоном та карамелізованою грушею",
    219: "Теплий салат з телятиною",
    55: "Салат цезарь",
    40: "Грецький салат",
    234: "Пісний овочевий з горіховою заправкою",
    53: "Овочевий салат з горіховою заправкою",
    273: "Легкий салат з запеченим гарбузом",
    438: "Мікс салату з куркою сувід",
    288: "Крем-суп гарбузовий з беконом",
    262: "Крем-суп грибний з грінками",
    37: "Суп Вушка",
    42: "М'ясна солянка",
    206: "Окрошка на айрані з ковбасою",
    384: "Окрошка на айрані з язиком телячим, 300 г",
    44: "Манти з яловичиною (класичні)",
    521: "Пельмені з філе курки",
    429: "Манти з сиром та зеленью",
    9: "Манти з яловичиною та свининою",
    497: "Пельмені як мають бути з телятиною",
    51: "Деруни з вершковим соусом та грибами",
    49: "Деруни зі сметаною",
    252: "Картопля по-селянськи з грибами",
    503: "Картопля селянка",
    229: "Жульєн",
    387: "Бадриджани з крем сиром та волоським горіхом",
    363: "Стріпси з філе молодої курки",
    397: "Оливковий мікс",
    68: "Картопля Фрі з соусами",
    67: "Сирна тарілка",
    69: "Сирні хрусткі палички",
    403: "Батат фрі з соусом цезар та пармезаном",
    63: "Млинці солодкі з ванільним сиром",
    61: "Млинці с куркою та грибами",
    66: "Млинці с куркою",
    47: "Сирники",
    57: "Сирні солодкі кульки",
    64: "Млинці ажурні без начинки",
    353: "Класика",
    540: "Вафельний десерт з натяком на рафаело, 115 г",
    214: "Шоколадний фондан",
    331: "Чизкейк LA",
    401: "Ніжне крем -брюле",
    526: "Борщ Український",
    276: "Сніданок 'Субмарина'",
    440: "Сніданок 'Шакшука'",
    444: "Сніданок 'Як вдома'",
    275: "Сніданок 'Бюргер'",
    274: "Сніданок 'Фрітата'",
}

# ======================
# Объединяем группы
# ======================
GROUPS = {**CHEBUREK_GROUPS, **YANTYK_GROUPS, **PIDE_GROUP}

last_update = 0
cache = {"hot": {}, "cold": {}}


def fetch_sales(group_mode=True):
    """Получаем продажи из Poster API за текущий день"""
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
        return {"total": 0, "top": []}

    sales_count = {}
    total_orders = 0

    for item in data:
        name = item.get("product_name", "").strip()
        quantity = int(float(item.get("count", 0)))
        product_id = int(item.get("product_id", 0))

        if group_mode:  # Горячий цех
            # Проверяем группы
            for main_name, variants in GROUPS.items():
                if name in variants:
                    key = "Чебуреки/Янтики" if main_name in ["Чебуреки", "Янтики"] else main_name
                    sales_count[key] = sales_count.get(key, 0) + quantity
                    total_orders += quantity
                    break
            else:
                # Проверяем HOT_DISHES
                if product_id in HOT_DISHES:
                    sales_count[HOT_DISHES[product_id]] = sales_count.get(
                        HOT_DISHES[product_id], 0
                    ) + quantity
                    total_orders += quantity
        else:  # Холодный цех
            if product_id in COLD_DISHES:
                sales_count[COLD_DISHES[product_id]] = sales_count.get(
                    COLD_DISHES[product_id], 0
                ) + quantity
                total_orders += quantity

    # Берем топ-3 без "ТОП"
    top = sorted(sales_count.items(), key=lambda x: x[1], reverse=True)[:3]

    return {"total": total_orders, "top": [(i, c) for i, c in top]}


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
            .updated { margin-top: 10px; font-size: 18px; color: #aaa; }
            @keyframes fadeIn { from {opacity: 0;} to {opacity: 1;} }
        </style>
    </head>
    <body>
        <div class="grid">
            <div class="block hot">
                <h2>🔥 Гарячий ЦЕХ</h2>
                <p id="hot_total" style="font-size:32px; font-weight:bold;">Всього: ...</p>
                <div id="hot_top">Загрузка...</div>
            </div>
            <div class="block cold">
                <h2>❄️ Холодний ЦЕХ</h2>
                <p id="cold_total" style="font-size:32px; font-weight:bold;">Всього: ...</p>
                <div id="cold_top">Загрузка...</div>
            </div>
        </div>
        <div class="total" id="all_total">Загальна кількість замовлень: ...</div>
        <div class="updated" id="updated_time">Оновлено: ...</div>

        <script>
        async function updateData() {
            try {
                const hotRes = await fetch('/api/hot');
                const hot = await hotRes.json();
                document.getElementById('hot_total').innerText = "Всього: " + hot.total + " замовлень";
                let hotDiv = document.getElementById('hot_top');
                hotDiv.innerHTML = "";
                hot.top.forEach((item, index) => {
                    hotDiv.innerHTML += `<div class="item">${index+1}) ${item[0]} — ${item[1]} шт.</div>`;
                });

                const coldRes = await fetch('/api/cold');
                const cold = await coldRes.json();
                document.getElementById('cold_total').innerText = "Всього: " + cold.total + " замовлень";
                let coldDiv = document.getElementById('cold_top');
                coldDiv.innerHTML = "";
                cold.top.forEach((item, index) => {
                    coldDiv.innerHTML += `<div class="item">${index+1}) ${item[0]} — ${item[1]} шт.</div>`;
                });

                const all = hot.total + cold.total;
                const totalDiv = document.getElementById('all_total');
                totalDiv.innerText = "Загальна кількість замовлень: " + all;
                totalDiv.style.color = all > 100 ? "lime" : (all > 50 ? "yellow" : "red");

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
