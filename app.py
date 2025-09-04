import os
import requests
from flask import Flask, jsonify, render_template_string

app = Flask(__name__)

# === НАСТРОЙКИ ===
POSTER_TOKEN = '687409:4164553abf6a031302898da7800b59fb'
TRANSACTIONS_URL = 'https://joinposter.com/api/transactions.getTransactions'
DATE_FROM = '2024-07-01'
DATE_TO = '2024-09-01'

CHEBUREKI_IDS = {
    "14--NW", "8--NW", "243--NW", "327--NW-NOMOD", "347--NW",
    "12--NW", "13--NW", "244--NW", "502--NW-NOMOD", "349--NW",
    "74--NW", "73--NW", "75--NW", "76--NW", "375--NW"
}

PIDE_IDS = {
    "210--NW", "545--NW-NOMOD", "209--NW", "360--NW", "208--NW"
}


def fetch_transactions():
    params = {
        'token': POSTER_TOKEN,
        'date_from': DATE_FROM,
        'date_to': DATE_TO,
        'per_page': 100,
        'page': 1
    }

    che_total = 0
    pide_total = 0

    while True:
        response = requests.get(TRANSACTIONS_URL, params=params)
        data = response.json()

        transactions = data.get("response", {}).get("data", [])
        if not transactions:
            break

        for tx in transactions:
            products = tx.get("products", [])
            for p in products:
                product_code = p.get("product_code") or p.get("product_id")
                quantity = float(p.get("num", 0))
                if product_code in CHEBUREKI_IDS:
                    che_total += quantity
                elif product_code in PIDE_IDS:
                    pide_total += quantity

        if len(transactions) < params['per_page']:
            break
        params['page'] += 1

    return int(che_total), int(pide_total)


@app.route('/')
@app.route('/start')
def index():
    chebureki_count, pide_count = fetch_transactions()
    html = f"""
    <html>
    <head><title>Продажи</title></head>
    <body style="font-family: Arial; padding: 40px;">
        <h1>Отчет по продажам</h1>
        <ul>
            <li><strong>Чебуреки и Янтики:</strong> {chebureki_count} шт</li>
            <li><strong>Піде:</strong> {pide_count} шт</li>
        </ul>
    </body>
    </html>
    """
    return render_template_string(html)


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
