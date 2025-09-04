from flask import Flask, jsonify
import requests
import os

app = Flask(__name__)

# Получение токена из переменной окружения (как указано в твоей инструкции на GitHub)
POSTER_TOKEN = os.getenv("POSTER_TOKEN")

# Тестовый endpoint для проверки, работает ли сервис
@app.route('/')
def home():
    return '✅ Kitchen Dashboard is running!'

# Пример запроса к Poster API — получение категорий меню
@app.route('/menu/categories')
def get_categories():
    url = f'https://joinposter.com/api/menu.getCategories?token={POSTER_TOKEN}&fiscal=0'
    try:
        response = requests.get(url)
        return jsonify(response.json())
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Обязательная конструкция для корректного запуска на Render
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
