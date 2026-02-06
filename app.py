import os
import time
import requests
import sys
from datetime import date, datetime, timedelta
from flask import Flask, render_template_string, jsonify

app = Flask(__name__)

# ==== Конфиг ====
ACCOUNT_NAME = "poka-net3"
POSTER_TOKEN = os.getenv("POSTER_TOKEN")
CHOICE_TOKEN = os.getenv("CHOICE_TOKEN")
WEATHER_KEY = os.getenv("WEATHER_KEY", "")
# Группа 3.2 для Софиевской Борщаговки (ул. Мира)
POWER_GROUP = "3.2"

# Категории POS ID
HOT_CATEGORIES  = {4, 13, 15, 46, 33}
COLD_CATEGORIES = {7, 8, 11, 16, 18, 19, 29, 32, 36, 44}
BAR_CATEGORIES  = {9,14,27,28,34,41,42,47,22,24,25,26,39,30}

# Кэш
PRODUCT_CACHE = {}
PRODUCT_CACHE_TS = 0
CACHE = {
    "hot": {}, "cold": {}, "hot_prev": {}, "cold_prev": {},
    "hourly": {}, "hourly_prev": {}, "hourly_year": {}, "share": {}
}
CACHE_TS = 0
BOOKINGS_CACHE = []
BOOKINGS_CACHE_TS = 0

POWER_CACHE = {"status": "Оновлення...", "next": "", "has_power": True, "icon": "🟢"}
POWER_CACHE_TS = 0

# ===== Helpers =====
def _get(url, **kwargs):
    r = requests.get(url, timeout=kwargs.pop("timeout", 10), **kwargs)
    return r.json().get("response", [])

def get_poster_data(date_from, date_to):
    url = f"https://joinposter.com/api/dash.getAnalytics?token={POSTER_TOKEN}&dateFrom={date_from}&dateTo={date_to}&type=category"
    return _get(url)

def get_hourly_data(date_val):
    url = f"https://joinposter.com/api/dash.getAnalytics?token={POSTER_TOKEN}&dateFrom={date_val}&dateTo={date_val}&type=hours"
    return _get(url)

# ===== Power Status Logic =====
def fetch_power_status():
    global POWER_CACHE, POWER_CACHE_TS
    if time.time() - POWER_CACHE_TS < 300 and POWER_CACHE["status"] != "Оновлення...":
        return POWER_CACHE
    
    try:
        url = "https://app.yasno.ua/api/v1/pages/home/schedule-turn-off-electricity"
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=10)
        
        if r.status_code == 200:
            res_data = r.json()
            group_schedule = []
            
            # Проверка разных структур API
            components = res_data.get("components", [])
            for comp in components:
                if "schedule" in comp:
                    group_schedule = comp["schedule"].get(POWER_GROUP, [])
                    break
            if not group_schedule:
                group_schedule = res_data.get("schedule", {}).get(POWER_GROUP, [])

            if not group_schedule:
                return {"status": "Немає графіку", "next": "Перевірте групу", "has_power": True, "icon": "🟢"}

            now = datetime.now()
            current_outage_end = None
            next_outage_start = None

            for period in group_schedule:
                try:
                    start_dt = datetime.fromisoformat(period["start"].replace('Z', ''))
                    end_dt = datetime.fromisoformat(period["end"].replace('Z', ''))
                    if start_dt <= now <= end_dt:
                        current_outage_end = end_dt
                        break
                    elif start_dt > now:
                        if next_outage_start is None or start_dt < next_outage_start:
                            next_outage_start = start_dt
                except: continue

            if current_outage_end:
                POWER_CACHE = {"status": "Немає світла", "next": f"Включать о {current_outage_end.strftime('%H:%M')}", "has_power": False, "icon": "🔴"}
            elif next_outage_start:
                delta = next_outage_start - now
                h, m = int(delta.total_seconds() // 3600), int((delta.total_seconds() % 3600) // 60)
                time_str = f"через {h}г {m}хв" if h > 0 else f"через {m}хв"
                POWER_CACHE = {"status": "Є світло", "next": f"Відключать {time_str}", "has_power": True, "icon": "🟢"}
            else:
                POWER_CACHE = {"status": "Є світло", "next": "Змін не передбачено", "has_power": True, "icon": "🟢"}
            
            POWER_CACHE_TS = time.time()
            return POWER_CACHE
    except:
        pass
    return POWER_CACHE

# ===== Routes =====
@app.route('/api/data')
def api_data():
    global CACHE, CACHE_TS
    if time.time() - CACHE_TS < 60: return jsonify(CACHE)
    
    today = date.today().strftime('%Y%m%d')
    last_week = (date.today() - timedelta(days=7)).strftime('%Y%m%d')
    last_year = (date.today() - timedelta(days=364)).strftime('%Y%m%d')
    
    raw_today = get_poster_data(today, today)
    raw_prev = get_poster_data(last_week, last_week)
    
    # Распределение по цехам
    h_now = sum(float(i['revenue']) for i in raw_today if int(i['category_id']) in HOT_CATEGORIES) / 100
    c_now = sum(float(i['revenue']) for i in raw_today if int(i['category_id']) in COLD_CATEGORIES) / 100
    b_now = sum(float(i['revenue']) for i in raw_today if int(i['category_id']) in BAR_CATEGORIES) / 100
    
    h_old = sum(float(i['revenue']) for i in raw_prev if int(i['category_id']) in HOT_CATEGORIES) / 100
    c_old = sum(float(i['revenue']) for i in raw_prev if int(i['category_id']) in COLD_CATEGORIES) / 100
    
    # Почасовая статистика
    h_today = get_hourly_data(today)
    h_last_week = get_hourly_data(last_week)
    h_last_year = get_hourly_data(last_year)

    CACHE = {
        "hot": {"now": h_now, "old": h_old},
        "cold": {"now": c_now, "old": c_old},
        "share": {"hot": h_now, "cold": c_now, "bar": b_now},
        "hourly": {i['hour']: float(i['revenue'])/100 for i in h_today},
        "hourly_prev": {i['hour']: float(i['revenue'])/100 for i in h_last_week},
        "hourly_year": {i['hour']: float(i['revenue'])/100 for i in h_last_year}
    }
    CACHE_TS = time.time()
    return jsonify(CACHE)

@app.route('/api/tables')
def api_tables():
    url = f"https://joinposter.com/api/clients.getTables?token={POSTER_TOKEN}"
    tabs = _get(url)
    res = {"hall": [], "terrace": []}
    for t in tabs:
        info = {"id": t['table_id'], "name": t['table_name'], "status": int(t['status']), "waiter": t.get('waiter_name', '')}
        if int(t['hall_id']) == 1: res["hall"].append(info)
        else: res["terrace"].append(info)
    return jsonify(res)

@app.route('/api/bookings')
def api_bookings():
    global BOOKINGS_CACHE, BOOKINGS_CACHE_TS
    if time.time() - BOOKINGS_CACHE_TS < 600: return jsonify(BOOKINGS_CACHE)
    try:
        url = "https://api.choiceqr.com/api/v1/bookings/active"
        r = requests.get(url, headers={"Authorization": f"Bearer {CHOICE_TOKEN}"}, timeout=10)
        BOOKINGS_CACHE = r.json().get("data", [])[:5]
        BOOKINGS_CACHE_TS = time.time()
    except: pass
    return jsonify(BOOKINGS_CACHE)

@app.route('/api/power')
def api_power():
    return jsonify(fetch_power_status())

@app.route('/api/weather')
def api_weather():
    if not WEATHER_KEY: return jsonify({"temp": "--", "desc": "No Key"})
    try:
        url = f"https://api.openweathermap.org/data/2.5/weather?q=Kyiv&units=metric&appid={WEATHER_KEY}&lang=uk"
        w = requests.get(url).json()
        return jsonify({"temp": round(w['main']['temp']), "desc": w['weather'][0]['description'].capitalize()})
    except: return jsonify({"temp": "??", "desc": "Error"})

@app.route('/')
def index():
    template = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Kitchen Dashboard</title>
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <style>
            body { background: #1a1a1a; color: white; font-family: sans-serif; margin: 0; padding: 15px; overflow: hidden; }
            .grid { display: grid; grid-template-columns: 2fr 1fr; grid-template-rows: 1fr 1fr; gap: 15px; height: 95vh; }
            .card { background: #2d2d2d; border-radius: 12px; padding: 15px; box-shadow: 0 4px 15px rgba(0,0,0,0.5); position: relative; }
            h2 { margin: 0 0 10px 0; color: #aaa; font-size: 1.2em; text-transform: uppercase; }
            
            /* Блок Часы и Свет */
            .top-info { position: absolute; top: 15px; right: 20px; text-align: right; z-index: 10; }
            #clock { font-size: 2.8em; font-weight: bold; margin-bottom: 5px; }
            .power-status { 
                background: rgba(0,0,0,0.4); padding: 8px 12px; border-radius: 10px; 
                display: inline-block; border: 1px solid #444; 
            }
            .has-power { color: #2ecc71; }
            .no-power { color: #e74c3c; }

            /* Продажи */
            .stats-row { display: flex; gap: 20px; margin-bottom: 15px; }
            .stat-item { flex: 1; }
            .stat-value { font-size: 2em; font-weight: bold; }
            .stat-label { font-size: 0.8em; color: #888; }
            .up { color: #2ecc71; } .down { color: #e74c3c; }

            /* Столы */
            .tables-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(60px, 1fr)); gap: 8px; }
            .table-box { 
                aspect-ratio: 1/1; border-radius: 8px; display: flex; flex-direction: column;
                align-items: center; justify-content: center; font-weight: bold; font-size: 0.9em;
                background: #3d3d3d; border: 2px solid #555;
            }
            .table-box.occupied { background: #e74c3c; border-color: #ff5e5e; }
            .table-box .waiter { font-size: 0.6em; font-weight: normal; margin-top: 2px; text-align: center; }

            .bookings-list { font-size: 0.9em; }
            .booking-item { padding: 5px 0; border-bottom: 1px solid #444; }
        </style>
    </head>
    <body>
        <div class="top-info">
            <div id="clock">00:00:00</div>
            <div id="weather" style="margin-bottom: 10px; color: #888;">Завантаження...</div>
            <div id="power-el" class="power-status">
                <span id="p-icon">🟢</span> <span id="p-status">Завантаження...</span>
                <div id="p-next" style="font-size: 0.7em; opacity: 0.8;"></div>
            </div>
        </div>

        <div class="grid">
            <div class="card">
                <h2>Виторг по годинах</h2>
                <div class="stats-row">
                    <div class="stat-item">
                        <div class="stat-label">Гарячий цех</div>
                        <div id="hot-val" class="stat-value">0</div>
                    </div>
                    <div class="stat-item">
                        <div class="stat-label">Холодний цех</div>
                        <div id="cold-val" class="stat-value">0</div>
                    </div>
                </div>
                <canvas id="salesChart"></canvas>
            </div>

            <div class="card" style="overflow-y: auto;">
                <h2>Зали (Зал / Тераса)</h2>
                <div id="tables-hall" class="tables-grid" style="margin-bottom: 20px;"></div>
                <div id="tables-terrace" class="tables-grid"></div>
            </div>

            <div class="card">
                <h2>Розподіл замовлень</h2>
                <canvas id="shareChart"></canvas>
            </div>

            <div class="card">
                <h2>Бронювання (Choice)</h2>
                <div id="bookings" class="bookings-list"></div>
            </div>
        </div>

        <script>
        let salesChart, shareChart;

        function updateClock() {
            const now = new Date();
            document.getElementById('clock').textContent = now.toLocaleTimeString('uk-UA');
        }
        setInterval(updateClock, 1000);

        async function refresh() {
            try {
                const [dataRes, weatherRes, powerRes] = await Promise.all([
                    fetch('/api/data'), fetch('/api/weather'), fetch('/api/power')
                ]);
                
                const data = await dataRes.json();
                const weather = await weatherRes.json();
                const power = await powerRes.json();

                // Погода
                document.getElementById('weather').textContent = `${weather.temp}°C, ${weather.desc}`;

                // Свет
                const pEl = document.getElementById('power-el');
                document.getElementById('p-icon').textContent = power.icon;
                document.getElementById('p-status').textContent = power.status;
                document.getElementById('p-next').textContent = power.next;
                pEl.className = 'power-status ' + (power.has_power ? 'has-power' : 'no-power');

                // Цифры
                document.getElementById('hot-val').textContent = Math.round(data.hot.now) + ' ₴';
                document.getElementById('cold-val').textContent = Math.round(data.cold.now) + ' ₴';

                // График линий
                const hours = Array.from({length: 24}, (_, i) => i);
                const chartData = {
                    labels: hours,
                    datasets: [
                        { label: 'Сьогодні', data: hours.map(h => data.hourly[h] || 0), borderColor: '#3498db', tension: 0.3, fill: true, backgroundColor: 'rgba(52,152,219,0.1)' },
                        { label: 'Мин. тиждень', data: hours.map(h => data.hourly_prev[h] || 0), borderColor: '#555', borderDash: [5,5], tension: 0.3 }
                    ]
                };

                if(!salesChart) {
                    salesChart = new Chart(document.getElementById('salesChart'), {
                        type: 'line',
                        data: chartData,
                        options: { responsive: true, maintainAspectRatio: false, scales: { y: { beginAtZero: true } } }
                    });
                } else {
                    salesChart.data = chartData;
                    salesChart.update('none');
                }

                // Пирог
                const shareData = {
                    labels: ['Гарячий', 'Холодний', 'Бар'],
                    datasets: [{
                        data: [data.share.hot, data.share.cold, data.share.bar],
                        backgroundColor: ['#e74c3c', '#3498db', '#f1c40f']
                    }]
                };
                if(!shareChart) {
                    shareChart = new Chart(document.getElementById('shareChart'), {
                        type: 'doughnut',
                        data: shareData,
                        options: { responsive: true, maintainAspectRatio: false }
                    });
                } else {
                    shareChart.data = shareData;
                    shareChart.update();
                }

            } catch(e) { console.error(e); }
        }

        async function refreshTables() {
            const r = await fetch('/api/tables');
            const data = await r.json();
            const draw = (id, list) => {
                const el = document.getElementById(id);
                el.innerHTML = list.map(t => `
                    <div class="table-box ${t.status === 1 ? 'occupied' : ''}">
                        ${t.name}
                        <div class="waiter">${t.waiter || ''}</div>
                    </div>
                `).join('');
            };
            draw('tables-hall', data.hall);
            draw('tables-terrace', data.terrace);
        }

        async function refreshBookings() {
            const r = await fetch('/api/bookings');
            const data = await r.json();
            document.getElementById('bookings').innerHTML = data.map(b => `
                <div class="booking-item">
                    <b>${b.time || ''}</b> — ${b.name || 'Гість'} (${b.persons || '?'} чол)
                </div>
            `).join('');
        }

        refresh(); refreshTables(); refreshBookings();
        setInterval(refresh, 60000);
        setInterval(refreshTables, 30000);
        setInterval(refreshBookings, 600000);
        </script>
    </body>
    </html>
    """
    return render_template_string(template)

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
