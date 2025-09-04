import os
import requests
from flask import Flask, render_template_string
from datetime import datetime

app = Flask(__name__)

# Токен берется из переменной окружения
POSTER_TOKEN = os.getenv("POSTER_TOKEN")

if not POSTER_TOKEN:
    raise Exception("❌ Не найден POSTER_TOKEN. Установи переменную окружения.")

# ID товаров
CHEBUREKI_YANTYKI_IDS = {
    "14", "8", "243", "327", "347", "12", "13",  # Чебуреки
    "244", "502", "349", "74", "73", "75", "76", "375"  # Янтики
}
PIDE_IDS = {
    "210", "545", "209", "360", "208"
}

# Получение продаж за сегодня
def fetch_today_sales():
    today = datetime.now().strftime("%Y-%m-%d")

    url = f"https://joinposter.com/api/transactions.getTransactions?token={POSTER_TOKEN}&date_from={today}&date_to={today}"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json().get("response", {}).get("data", [])
    except Exception as e:
        print(f"❌ Ошибка при запросе данных: {e}")
        return 0, 0

    chebureki_count = 0
    pide_count = 0

    for transaction in data:
        for product in transaction.get("products", []):
            product_id = str(product.get("product_id"))
            num = int(product.get("num", 0))

            if product_id in CHEBUREKI_YANTYKI_IDS:
                chebureki_count += num
            elif product_id in PIDE_IDS:
                pide_count += num

    return chebureki_count, pide_count


# HTML-шаблон
HTML = """
<!DOCTYPE html>
<html lang="uk">
<head>
    <meta charset="UTF-8">
    <title>Дашборд продажів</title>
    <meta http-equiv="refresh" content="30"> <!-- автообновление каждые 30 сек -->
    <style>
        body { font-family: Arial, sans-serif; background: #111; color: #fff; text-align: center; padding: 50px; }
        h1 { font-size: 48px; }
        .value { font-size: 80px; margin: 20px 0; }
        .label { font-size: 24px; color: #ccc; }
    </style>
</head>
<body>
    <h1>📊 Продажі за сьогодні</h1>
    <div class="value">{{ chebureki }}</div>
    <div class="label">Чебуреки + Янтики</div>
    <div class="value">{{ pide }}</div>
    <div class="label">Піде</div>
    <p style="margin-top: 50px; color: #666;">Оновлюється кожні 30 секунд</p>
</body>
</html>
"""

# Маршрут на главную страницу
@app.route('/')
def dashboard():
    chebureki, pide = fetch_today_sales()
    return render_template_string(HTML, chebureki=chebureki, pide=pide)

# Запуск
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
