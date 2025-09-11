import os
import time
import requests
import sys
from datetime import date, datetime
from flask import Flask, render_template_string, jsonify

app = Flask(__name__)

POSTER_TOKEN = os.getenv("POSTER_TOKEN")
ACCOUNT_NAME = "poka-net3"

# ======================
# Словари цехов
# ======================
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
    401: "Ніжне крем-брюле",
    276: "Сніданок 'Субмарина'",
    440: "Сніданок 'Шакшука'",
    444: "Сніданок 'Як вдома'",
    275: "Сніданок 'Бюргер'",
    274: "Сніданок 'Фрітата'",
}

# ======================
# Кэш
# ======================
last_update = {"hot": 0, "cold": 0, "timeline": 0}
cache = {"hot": {}, "cold": {}, "timeline": {}}


def fetch_sales(dishes_dict):
    """Получаем продажи для заданного цеха"""
    today = date.today().strftime("%Y-%m-%d")
    url = f"https://{ACCOUNT_NAME}.joinposter.com/api/dash.getProductsSales?token={POSTER_TOKEN}&date_from={today}&date_to={today}"
    resp = requests.get(url)
    try:
        data = resp.json().get("response", [])
    except Exception as e:
        print("ERROR parsing JSON:", e, file=sys.stderr, flush=True)
        return {"total": 0, "top3": []}

    sales_count, total_orders = {}, 0
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


def fetch_timeline():
    """График заказов по часам"""
    today = date.today().strftime("%Y-%m-%d")
    url = f"https://{ACCOUNT_NAME}.joinposter.com/api/dash.getProductsSales?token={POSTER_TOKEN}&date_from={today}&date_to={today}"
    resp = requests.get(url)
    try:
        data = resp.json().get("response", [])
    except Exception as e:
        print("ERROR parsing JSON:", e, file=sys.stderr, flush=True)
        return {}

    timeline = {}
    for item in data:
        count = int(float(item.get("count", 0)))
        # Берем время модификации из поля left/right или просто текущий час (если нет)
        hour = datetime.now().hour
        timeline[hour] = timeline.get(hour, 0) + count

    # Преобразуем в массив
    labels = [f"{h:02d}:00" for h in range(24)]
    values = [timeline.get(h, 0) for h in range(24)]
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
    template = """
    <html>
    <head>
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <style>
            body { font-family: Arial, sans-serif; background: #111; color: #eee; text-align: center; }
            h2 { font-size: 40px; margin-bottom: 20px; }
            .grid { display: flex; justify-content: center; gap: 50px; max-width: 1400px; margin: auto; }
            .block { width: 650px; padding: 30px; border-radius: 15px; box-shadow: 0 0 20px rgba(0,0,0,0.7); }
            .hot { border: 4px solid #ff6600; }
            .cold { border: 4px solid #0099ff; }
            .item { font-size: 28px; margin: 8px 0; }
            .total { margin-top: 40px; font-size: 34px; font-weight: bold; }
            .updated { margin-top: 10px; font-size: 18px; color: #aaa; }
            canvas { margin-top: 40px; background: #222; border-radius: 10px; padding: 20px; }
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
        <div class="updated" id="updated_time">Оновлено: ...</div>

        <canvas id="ordersChart" width="1200" height="400"></canvas>

        <script>
        function medal(index) {
            if (index === 0) return "🥇";
            if (index === 1) return "🥈";
            if (index === 2) return "🥉";
            return "";
        }

        let chart;

        async function updateData() {
            const hot = await (await fetch('/api/hot')).json();
            const cold = await (await fetch('/api/cold')).json();
            const timeline = await (await fetch('/api/timeline')).json();

            document.getElementById('hot_total').innerText = "Всього: " + hot.total + " замовлень";
            let hotDiv = document.getElementById('hot_top3');
            hotDiv.innerHTML = "🏆 ТОП-3 продажі:";
            hot.top3.forEach((item, index) => {
                hotDiv.innerHTML += `<div class="item">${medal(index)} ${item[0]} — ${item[1]}</div>`;
            });

            document.getElementById('cold_total').innerText = "Всього: " + cold.total + " замовлень";
            let coldDiv = document.getElementById('cold_top3');
            coldDiv.innerHTML = "🏆 ТОП-3 продажі:";
            cold.top3.forEach((item, index) => {
                coldDiv.innerHTML += `<div class="item">${medal(index)} ${item[0]} — ${item[1]}</div>`;
            });

            const all = hot.total + cold.total;
            const totalDiv = document.getElementById('all_total');
            totalDiv.innerText = "Загальна кількість замовлень: " + all;
            totalDiv.style.color = all > 100 ? "lime" : (all > 50 ? "yellow" : "red");

            const now = new Date();
            document.getElementById('updated_time').innerText = "Оновлено: " + now.toLocaleTimeString();

            // Обновляем график
            const ctx = document.getElementById('ordersChart').getContext('2d');
            if (chart) chart.destroy();
            chart = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: timeline.labels,
                    datasets: [{
                        label: 'Замовлення за годину',
                        data: timeline.values,
                        backgroundColor: '#00cc66'
                    }]
                },
                options: {
                    responsive: false,
                    plugins: { legend: { labels: { color: 'white' } } },
                    scales: {
                        x: { ticks: { color: 'white' } },
                        y: { ticks: { color: 'white' } }
                    }
                }
            });
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
