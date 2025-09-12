import os
import requests
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import io
import base64
from flask import Flask, jsonify, render_template_string
from datetime import datetime, timedelta

app = Flask(__name__)

# === Настройки ===
POSTER_TOKEN = os.getenv("POSTER_TOKEN", "687409:4164553abf6a031302898da7800b59fb")
POSTER_API = "https://poka-net3.joinposter.com/api"

# Горячий и холодный цех по category_id
HOT_CATEGORIES = [4, 13, 15, 46, 33]   # Чебуреки, Мясні, Янтики, Горячі страви, Піде
COLD_CATEGORIES = [7, 8, 11, 16, 18, 19, 29, 32, 36, 44]  # Манти, Деруни, Салати, Супи и т.д.


# === Функции ===

def get_transactions(date_from: str, date_to: str):
    """Получить список транзакций с Poster API"""
    url = f"{POSTER_API}/transactions.getTransactions"
    params = {
        "token": POSTER_TOKEN,
        "date_from": date_from,
        "date_to": date_to,
        "per_page": 500,
        "page": 1,
    }
    res = requests.get(url, params=params)
    data = res.json()
    return data.get("response", {}).get("data", [])


def get_hourly_sales(target_date: datetime):
    """Посчитать почасовые продажи по горячему и холодному цеху"""
    date_str = target_date.strftime("%Y-%m-%d")
    transactions = get_transactions(date_str, date_str)

    hourly_hot = {h: 0 for h in range(10, 23)}
    hourly_cold = {h: 0 for h in range(10, 23)}

    for tx in transactions:
        close_time = datetime.strptime(tx["date_close"], "%Y-%m-%d %H:%M:%S")
        hour = close_time.hour
        if 10 <= hour <= 22:
            for p in tx.get("products", []):
                category_id = int(p.get("category_id", 0)) if "category_id" in p else None
                count = float(p.get("num", 0))
                if category_id in HOT_CATEGORIES:
                    hourly_hot[hour] += count
                elif category_id in COLD_CATEGORIES:
                    hourly_cold[hour] += count

    # Делаем накопительные суммы
    hot_cumulative = []
    cold_cumulative = []
    total_hot = 0
    total_cold = 0
    for h in range(10, 23):
        total_hot += hourly_hot[h]
        total_cold += hourly_cold[h]
        hot_cumulative.append(total_hot)
        cold_cumulative.append(total_cold)

    return hot_cumulative, cold_cumulative


def generate_chart():
    """Сгенерировать график с текущим днём и прошлой неделей"""
    today = datetime.now()
    last_week = today - timedelta(days=7)

    hot_today, cold_today = get_hourly_sales(today)
    hot_last, cold_last = get_hourly_sales(last_week)

    hours = list(range(10, 23))
    now_hour = today.hour

    # Ограничиваем данные текущим временем (обрезаем будущее)
    cutoff_index = max(0, min(len(hours), now_hour - 10 + 1))
    hot_today = hot_today[:cutoff_index]
    cold_today = cold_today[:cutoff_index]
    hours_today = hours[:cutoff_index]

    plt.figure(figsize=(10, 4))
    # Текущий день (жирные линии)
    plt.plot(hours_today, hot_today, color="orange", linewidth=2.5, label="Гарячий (сьогодні)")
    plt.plot(hours_today, cold_today, color="deepskyblue", linewidth=2.5, label="Холодний (сьогодні)")

    # Прошлая неделя (пунктир)
    plt.plot(hours, hot_last, color="orange", linestyle="--", linewidth=1.8, label="Гарячий (мин. тиждень)")
    plt.plot(hours, cold_last, color="deepskyblue", linestyle="--", linewidth=1.8, label="Холодний (мин. тиждень)")

    plt.title("📊 Завантаженість кухні", fontsize=14, fontweight="bold")
    plt.xlabel("Година")
    plt.ylabel("Кількість замовлень (накопич.)")
    plt.xticks(hours)
    plt.grid(True, linestyle="--", alpha=0.3)
    plt.legend()
    plt.tight_layout()

    # Сохраняем график в base64
    img = io.BytesIO()
    plt.savefig(img, format="png", transparent=True)
    img.seek(0)
    graph_url = base64.b64encode(img.getvalue()).decode()
    plt.close()
    return f"data:image/png;base64,{graph_url}"


# === Роуты ===

@app.route("/")
def dashboard():
    chart_url = generate_chart()
    template = """
    <html>
    <head>
      <meta charset="utf-8">
      <style>
        body { background: #111; color: white; font-family: Inter, sans-serif; }
        .block { border: 2px solid orange; border-radius: 12px; padding: 10px; margin: 10px; text-align: center; }
        img { max-width: 100%; }
      </style>
    </head>
    <body>
      <div class="block">
        <img src="{{chart_url}}" />
      </div>
    </body>
    </html>
    """
    return render_template_string(template, chart_url=chart_url)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
