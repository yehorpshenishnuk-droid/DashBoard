from flask import Flask, render_template_string
import requests
from datetime import date

app = Flask(__name__)

# Токен Poster
API_TOKEN = '687409:4164553abf6a031302898da7800b59fb'

# ID нужных продуктов
CHEBUREKI_YANTYKY_IDS = [
    '14', '8', '243', '327', '347', '12', '13',  # Чебуреки
    '244', '502', '349', '74', '73', '75', '76', '375'  # Янтики
]

PIDE_IDS = [
    '210', '545', '209', '360', '208'
]

def get_today_transactions():
    today = date.today().isoformat()
    url = f"https://joinposter.com/api/transactions.getTransactions"
    params = {
        "token": API_TOKEN,
        "date_from": today,
        "date_to": today,
        "per_page": 100,
        "page": 1
    }

    all_products = []

    while True:
        response = requests.get(url, params=params).json()
        data = response.get("response", {}).get("data", [])
        if not data:
            break

        for transaction in data:
            products = transaction.get("products", [])
            for product in products:
                all_products.append(product)

        if len(data) < params["per_page"]:
            break
        else:
            params["page"] += 1

    return all_products

def calculate_sales(products):
    che_yan_count = 0
    pide_count = 0

    for product in products:
        pid = str(product.get("product_id"))
        qty = float(product.get("num", 0))

        if pid in CHEBUREKI_YANTYKY_IDS:
            che_yan_count += qty
        elif pid in PIDE_IDS:
            pide_count += qty

    return int(che_yan_count), int(pide_count)

@app.route("/")
def index():
    products = get_today_transactions()
    che_yan, pide = calculate_sales(products)

    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Статистика продаж</title>
        <style>
            body { font-family: Arial, sans-serif; text-align: center; padding: 40px; }
            h1 { font-size: 32px; }
            .box { font-size: 24px; margin: 20px 0; }
        </style>
    </head>
    <body>
        <h1>Отчет по продажам за сегодня</h1>
        <div class="box">Чебуреки и Янтики: {{ che_yan }} шт</div>
        <div class="box">Піде: {{ pide }} шт</div>
    </body>
    </html>
    """
    return render_template_string(html, che_yan=che_yan, pide=pide)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
