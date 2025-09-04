from flask import Flask, jsonify
import requests
import os

app = Flask(__name__)

# Замените на ваш токен, или добавьте переменную среды POSTER_TOKEN в Render
POSTER_TOKEN = os.environ.get('POSTER_TOKEN', '687409:4164553abf6a031302898da7800b59fb')

# Список POS ID для Чебуреков и Янтиков
CHEBUR_IDS = {
    '14--NW', '8--NW', '243--NW', '327--NW-NOMOD', '347--NW',
    '12--NW', '13--NW', '244--NW', '502--NW-NOMOD', '349--NW',
    '74--NW', '73--NW', '75--NW', '76--NW', '375--NW'
}

# POS ID для Піде (замени на свои реальные, если нужно)
PIDE_IDS = {
    'some-pide-id-1', 'some-pide-id-2'  # Заменить на реальные ID
}

# Получить список транзакций с Poster API
def get_transactions():
    url = f"https://joinposter.com/api/transactions.getTransactions"
    params = {
        'token': POSTER_TOKEN,
        'date_from': '2024-07-01',
        'date_to': '2024-09-01',
        'per_page': 100,
        'page': 1
    }

    all_transactions = []
    while True:
        resp = requests.get(url, params=params).json()
        data = resp.get('response', {}).get('data', [])
        if not data:
            break
        all_transactions.extend(data)
        params['page'] += 1
        if params['page'] > resp.get('response', {}).get('page', {}).get('count', 1):
            break
    return all_transactions

# Подсчитать количество проданных единиц по POS ID
def count_products(transactions):
    chebureki_count = 0
    pide_count = 0

    for trx in transactions:
        for product in trx.get('products', []):
            pos_id = product.get('product_id')
            quantity = int(product.get('num', 0))
            if pos_id in CHEBUR_IDS:
                chebureki_count += quantity
            elif pos_id in PIDE_IDS:
                pide_count += quantity
    return chebureki_count, pide_count

@app.route('/')
def dashboard():
    try:
        transactions = get_transactions()
        chebureki_count, pide_count = count_products(transactions)

        return jsonify({
            'Чебуреки и Янтики': f'{chebureki_count} шт',
            'Піде': f'{pide_count} шт'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Для запуска локально или на Render
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
