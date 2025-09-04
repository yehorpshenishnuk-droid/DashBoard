import os
import requests
from flask import Flask, jsonify
from datetime import datetime
from collections import Counter

app = Flask(__name__)

POSTER_TOKEN = os.environ.get("POSTER_TOKEN")
API_URL = "https://joinposter.com/api"

# POS IDs из твоих данных
CHEBUREK_YANTYK_IDS = [
    "14--NW", "8--NW", "243--NW", "327--NW-NOMOD", "347--NW", "12--NW", "13--NW",
    "244--NW", "502--NW-NOMOD", "349--NW", "74--NW", "73--NW", "75--NW", "76--NW", "375--NW"
]

PIDE_IDS = [
    "210--NW", "545--NW-NOMOD", "209--NW", "360--NW", "208--NW"
]

def get_transactions():
    url = f"{API_URL}/transactions.getTransactions"
    params = {
        "token": POSTER_TOKEN,
        "date_from": "2024-07-01",
        "date_to": "2024-09-01"
    }

    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        return response.json().get("response", {}).get("data", [])
    except Exception as e:
        print("API error:", e)
        return []

def count_items(transactions, target_ids):
    counter = Counter()
    for tx in transactions:
        for product in tx.get("products", []):
            if str(product.get("product_id")) in target_ids or str(product.get("product_id") + "--NW") in target_ids:
                counter["count"] += int(product.get("num", 0))
    return counter["count"]

@app.route("/")
def index():
    return "✅ Kitchen Dashboard is running!"

@app.route("/stats")
def stats():
    transactions = get_transactions()
    chebureki_yantyki_count = count_items(transactions, CHEBUREK_YANTYK_IDS)
    pide_count = count_items(transactions, PIDE_IDS)

    return jsonify({
        "Чебуреки и Янтики": f"{chebureki_yantyki_count} шт",
        "Піде": f"{pide_count} шт"
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
