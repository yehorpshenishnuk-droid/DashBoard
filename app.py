from flask import Flask
import requests
import datetime
import os

app = Flask(__name__)

POSTER_TOKEN = '687409:4164553abf6a031302898da7800b59fb'

# Получаем сегодняшнюю дату
def get_today_date():
    return datetime.datetime.now().strftime("%Y-%m-%d")

# Получаем все транзакции за сегодня
def get_transactions_for_today():
    url = 'https://joinposter.com/api/transactions.getTransactions'
    params = {
        'token': POSTER_TOKEN,
        'date_from': get_today_date(),
        'date_to': get_today_date(),
        'include_products': 'true',
        'per_page': 100,
        'page': 1
    }

    all_data = []
    while True:
        res = requests.get(url, params=params)
        data = res.json()

        if 'response' not in data or 'data' not in data['response']:
            break

        transactions = data['response']['data']
        if not transactions:
            break

        all_data.extend(transactions)
        if len(transactions) < params['per_page']:
            break
        params['page'] += 1

    return all_data

# Страница по умолчанию
@app.route("/")
def home():
    return "✅ Kitchen Dashboard is running!"

# DEBUG — список продуктов из транзакций
@app.route("/debug")
def debug():
    transactions = get_transactions_for_today()
    lines = []

    for tx in transactions:
        for product in tx.get("products", []):
            lines.append(f"{product}<br>")

    return f"<h3>DEBUG: продукты за {get_today_date()}</h3>" + "".join(lines)

# Для запуска сервера
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
