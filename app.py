from flask import Flask
import os

app = Flask(__name__)

@app.route("/")
def index():
    return "✅ Kitchen Dashboard is running!"

@app.route("/start")
def start():
    # Статические значения, можешь заменить на расчёт из API
    chebureki_yantyki_count = 300
    pide_count = 35

    html = f"""
    <!DOCTYPE html>
    <html lang="uk">
    <head>
        <meta charset="UTF-8">
        <title>Kitchen Dashboard</title>
    </head>
    <body>
        <h1>📊 Продажи на сегодня</h1>
        <ul>
            <li><strong>Чебуреки і Янтики:</strong> {chebureki_yantyki_count} шт</li>
            <li><strong>Піде:</strong> {pide_count} шт</li>
        </ul>
    </body>
    </html>
    """
    return html

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
