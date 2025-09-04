from flask import Flask
import requests
from datetime import date
import os

app = Flask(__name__)

POSTER_TOKEN = "687409:4164553abf6a031302898da7800b59fb"

# Список кодов продуктов
CHEBUREKI_IDS = {
    "14--NW", "8--NW", "243--NW", "327--NW-NOMOD", "347--NW",
    "12--NW", "13--NW", "244--NW", "502--NW-NOMOD", "349--NW",
    "74--NW", "73--NW", "75--NW", "76--NW", "375--NW"
}

PIDE_IDS = {
    "210--NW", "545--NW-NOMOD", "209--NW", "360--NW", "208--NW"
}

def get_sales_data():
    today = date.today().strftime('%Y-%m-%d')
    page = 1
    chebureki_total = 0
    pide_total = 0

    while True:
        url = f"https://joinposter.com/api/transactions.getTransactions?token={POSTER_TOKEN}&date_from={today}&date_to={today}&per_page=100&page={page}"
        response = requests.get(url)
        data = response.json()

        transactions = data.get("response", {}).get("data", [])
        if not transactions:
            break

        for t in transactions:
            for p in t.get("products", []):
                product_id = p.get("product_id")
                product_code = str(p.get("product_code", ""))

                if product_code in CHEBUREKI_IDS:
                    chebureki_total += float(p.get("num", 0))
                elif product_code in PIDE_IDS:
                    pide_total += float(p.get("num", 0))

        if len(transactions) < 100:
            break
        page += 1

    return int(chebureki_total), int(pide_total)

@app.route("/")
def index():
    return '<h2>✅ Kitchen Dashboard is running!</h2><br><a href="/start">Перейти к отчету</a>'

@app.route("/start")
def report():
    chebureki, pide = get_sales_data()

    html = f"""
    <h1>Отчет по продажам за сегодня</h1>
    <ul>
        <li><b>Чебуреки и Янтики:</b> {chebureki} шт</li>
        <li><b>Піде:</b> {pide} шт</li>
    </ul>
    """
    return html

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
