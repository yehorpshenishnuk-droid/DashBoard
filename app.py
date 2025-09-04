import os
import requests
from flask import Flask, render_template_string
from datetime import datetime

app = Flask(__name__)

POSTER_TOKEN = os.environ.get("POSTER_TOKEN")
POSTER_BASE_URL = "https://joinposter.com/api"

def get_poster_bookings():
    url = f"{POSTER_BASE_URL}/clients.getBookings"
    params = {"token": POSTER_TOKEN}
    try:
        response = requests.get(url, params=params)
        data = response.json().get("response", [])
        today = datetime.now().date().isoformat()
        return [b for b in data if b.get("date") == today]
    except Exception as e:
        print("Ошибка получения данных из Poster:", e)
        return []

@app.route("/")
def dashboard():
    bookings = get_poster_bookings()
    total = len(bookings)
    timeslots = [(b.get("time", "?"), b.get("persons", "?")) for b in bookings]

    return render_template_string("""
    <html>
        <head>
            <meta http-equiv="refresh" content="60">
            <style>
                body { font-family: sans-serif; padding: 20px; background: #fefefe; }
                h1 { font-size: 2em; }
                table { width: 100%; border-collapse: collapse; margin-top: 20px; }
                td, th { padding: 12px; border: 1px solid #ccc; text-align: center; }
            </style>
        </head>
        <body>
            <h1>🍽️ Бронирования на сегодня: {{ total }}</h1>
            <table>
                <tr><th>Время</th><th>Гостей</th></tr>
                {% for t in timeslots %}
                <tr><td>{{ t[0] }}</td><td>{{ t[1] }}</td></tr>
                {% endfor %}
            </table>
        </body>
    </html>
    """, total=total, timeslots=timeslots)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
