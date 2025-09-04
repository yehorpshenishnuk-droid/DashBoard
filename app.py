import os
import requests
from flask import Flask, jsonify

app = Flask(__name__)

POSTER_TOKEN = os.getenv("POSTER_TOKEN")

# ID продуктов (замени на свои при необходимости)
CHEBUREKI_YANTYKI_IDS = [
    "14", "8", "243", "327", "347", "12", "13",  # Чебуреки
    "244", "502", "349", "74", "73", "75", "76", "375"  # Янтики
]

PIDE_IDS = ["101", "102"]  # Примерные ID — укажи точные ID продуктов пиде


def get_transactions():
    url = f"https://joinposter.com/api/transactions.getTransactions"
    params = {
        "token": POSTER_TOKEN,
        "date_from": "2024-07-01",
        "date_to": "2024-09-01",
        "per_page": 1000
    }
    response = requests.get(url, params=params)
    return response.json()["response"]["data"]


def count_products(transactions):
    che_count = 0
    pide_count = 0

    for t in transactions:
        for product in t.get("products", []):
            product_id = str(product.get("product_id"))
            amount = int(product.get("num", 0))

            if product_id in CHEBUREKI_YANTYKI_IDS:
                che_count += amount
            elif product_id in PIDE_IDS:
                pide_count += amount

    return che_count, pide_count


@app.route("/")
def dashboard():
    try:
        transactions = get_transactions()
        chebureki_yantyki, pide = count_products(transactions)
        return jsonify({
            "Чебуреки и Янтики": f"{chebureki_yantyki} шт",
            "Пиде": f"{pide} шт"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True)
