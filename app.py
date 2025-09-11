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
    "Чебурек з телятиною": [
        "Чебурек з телятиною",
        "Чебурек з телятиною(+Мікс Сирів 20 г)",
        "Чебурек з телятиною (+Томати + Зелень, +Мікс Сирів)",
        "Чебурек з телятиною (+ суміш зелені, 10 г)",
        "Чебурек з телятиною (+Томати + Зелень)",
        "Чебурек з телятиною (+Сир чедер 12 г)",
    ],
    "Чебурек з свининою": [
        "Чебурек з свининою",
        "Чебурек з свининою(+Томати + Зелень, +Мікс Сирів)",
        "Чебурек з свининою(+ суміш зелені, 10 г)",
        "Чебурек з свининою(+Томати + Зелень)",
        "Чебурек з свининою(+Сир чедер 12 г)",
        "Чебурек з свининою(+Мікс Сирів 20 г)",
    ],
    "Чебурек з баранниною": [
        "Чебурек з баранниною",
        "Чебурек з баранниною (+Томати + Зелень, +Мікс Сирів)",
        "Чебурек з баранниною (+ суміш зелені, 10 г)",
        "Чебурек з баранниною (+Томати + Зелень)",
        "Чебурек з баранниною (+Сир чедер 12 г)",
        "Чебурек з баранниною(+Мікс Сирів 20 г)",
    ],
    "Чебурек з куркою": [
        "Чебурек з куркою",
        "Чебурек з куркою(+Томати + Зелень, +Мікс Сирів)",
        "Чебурек з куркою(+ суміш зелені, 10 г)",
        "Чебурек з куркою(+Томати + Зелень)",
        "Чебурек з куркою(+Сир чедер 12 г)",
        "Чебурек з куркою(+Мікс Сирів 20 г)",
    ],
    "Чебурек з сиром": [
        "Чебурек з сиром",
        "Чебурек з сиром(+Томати + Зелень, +Мікс Сирів)",
        "Чебурек з сиром(+ суміш зелені, 10 г)",
        "Чебурек з сиром(+Томати + Зелень)",
        "Чебурек з сиром(+Сир чедер 12 г)",
        "Чебурек з сиром(+Мікс Сирів 20 г)",
    ],
}

# ======================
# Группы Янтиків
# ======================
YANTYK_GROUPS = {
    "Янтик з телятиною": [
        "Янтик з телятиною",
        "Янтик з телятиною(+Мікс Сирів 20 г)",
        "Янтик з телятиною (+Томати + Зелень, +Мікс Сирів)",
        "Янтик з телятиною (+ суміш зелені, 10 г)",
        "Янтик з телятиною (+Томати + Зелень)",
        "Янтик з телятиною (+Сир чедер 12 г)",
    ],
    "Янтик з свининою": [
        "Янтик з свининою",
        "Янтик з свининою(+Томати + Зелень, +Мікс Сирів)",
        "Янтик з свининою(+ суміш зелені, 10 г)",
        "Янтик з свининою(+Томати + Зелень)",
        "Янтик з свининою(+Сир чедер 12 г)",
        "Янтик з свининою(+Мікс Сирів 20 г)",
    ],
    "Янтик з баранниною": [
        "Янтик з баранниною",
        "Янтик з баранниною (+Томати + Зелень, +Мікс Сирів)",
        "Янтик з баранниною (+ суміш зелені, 10 г)",
        "Янтик з баранниною (+Томати + Зелень)",
        "Янтик з баранниною (+Сир чедер 12 г)",
        "Янтик з баранниною(+Мікс Сирів 20 г)",
    ],
    "Янтик з куркою": [
        "Янтик з куркою",
        "Янтик з куркою(+Томати + Зелень, +Мікс Сирів)",
        "Янтик з куркою(+ суміш зелені, 10 г)",
        "Янтик з куркою(+Томати + Зелень)",
        "Янтик з куркою(+Сир чедер 12 г)",
        "Янтик з куркою(+Мікс Сирів 20 г)",
    ],
    "Янтик з сиром": [
        "Янтик з сиром",
        "Янтик з сиром(+Томати + Зелень, +Мікс Сирів)",
        "Янтик з сиром(+ суміш зелені, 10 г)",
        "Янтик з сиром(+Томати + Зелень)",
        "Янтик з сиром(+Сир чедер 12 г)",
        "Янтик з сиром(+Мікс Сирів 20 г)",
    ],
}

# ======================
# Холодний цех (фиксированный список)
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
}

# Объединяем группы
GROUPS = {**CHEBUREK_GROUPS, **YANTYK_GROUPS}

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
    print("DEBUG Poster API response:", resp.text[:200], file=sys.stderr, flush=True)

    try:
        data = resp.json().get("response", [])
    except Exception as e:
        print("ERROR parsing JSON:", e, file=sys.stderr, flush=True)
        return {"total": 0, "top3": [("Помилка", 0)]}

    sales_count = {}
    total_orders = 0

    for item in data:
        name = item.get("product_name", "").strip()
        quantity = int(float(item.get("count", 0)))
        product_id = int(item.get("product_id", 0))

        if group_mode:  # Горячий цех (группы)
            for main_name, variants in GROUPS.items():
                if name in variants:
                    sales_count[main_name] = sales_count.get(main_name, 0) + quantity
                    total_orders += quantity
                    break
        else:  # Холодный цех (по ID)
            if product_id in COLD_DISHES:
                sales_count[COLD_DISHES[product_id]] = sales_count.get(
                    COLD_DISHES[product_id], 0
                ) + quantity
                total_orders += quantity

    top3 = sorted(sales_count.items(), key=lambda x: x[1], reverse=True)[:3]

    return {"total": total_orders, "top3": [(i, c) for i, c in top3]}


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
                <div id="hot_top3">Загрузка...</div>
            </div>
            <div class="block cold">
                <h2>❄️ Холодний ЦЕХ</h2>
                <p id="cold_total" style="font-size:32px; font-weight:bold;">Всього: ...</p>
                <div id="cold_top3">Загрузка...</div>
            </div>
        </div>
        <div class="total" id="all_total">Загальна кількість замовлень: ...</div>
        <div class="updated" id="updated_time">Оновлено: ...</div>

        <script>
        function medal(index) {
            if (index === 0) return "🥇";
            if (index === 1) return "🥈";
            if (index === 2) return "🥉";
            return "";
        }

        async function updateData() {
            try {
                const hotRes = await fetch('/api/hot');
                const hot = await hotRes.json();
                document.getElementById('hot_total').innerText = "Всього: " + hot.total + " замовлень";
                let hotDiv = document.getElementById('hot_top3');
                hotDiv.innerHTML = "🏆 ТОП-3 продажі:";
                hot.top3.forEach((item, index) => {
                    hotDiv.innerHTML += `<div class="item">${medal(index)} ${item[0]} — ${item[1]}</div>`;
                });

                const coldRes = await fetch('/api/cold');
                const cold = await coldRes.json();
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
