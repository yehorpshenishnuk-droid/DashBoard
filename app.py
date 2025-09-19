import os
import time
import requests
import sys
from datetime import date, datetime, timedelta
from flask import Flask, render_template_string, jsonify

app = Flask(__name__)

# ==== Конфиг ====
ACCOUNT_NAME = "poka-net3"
POSTER_TOKEN = os.getenv("POSTER_TOKEN")           # обязателен
CHOICE_TOKEN = os.getenv("CHOICE_TOKEN")           # опционален (бронирования)
WEATHER_KEY = os.getenv("WEATHER_KEY", "")         # API ключ OpenWeather

# Категории POS ID
HOT_CATEGORIES  = {4, 13, 15, 46, 33}
COLD_CATEGORIES = {7, 8, 11, 16, 18, 19, 29, 32, 36, 44}
BAR_CATEGORIES  = {9,14,27,28,34,41,42,47,22,24,25,26,39,30}

# Кэш
PRODUCT_CACHE = {}
PRODUCT_CACHE_TS = 0
CACHE = {
    "hot": {}, "cold": {}, "hot_prev": {}, "cold_prev": {},
    "hourly": {}, "hourly_prev": {}, "share": {}, "tables": {}
}
CACHE_TS = 0

# ===== Helpers =====
def _get(url, **kwargs):
    r = requests.get(url, timeout=kwargs.pop("timeout", 25))
    log_snippet = r.text[:500].replace("\n", " ")
    print(f"DEBUG GET {url.split('?')[0]} -> {r.status_code} : {log_snippet}", file=sys.stderr, flush=True)
    r.raise_for_status()
    return r

# ===== Справочник товаров =====
def load_products():
    global PRODUCT_CACHE, PRODUCT_CACHE_TS
    if PRODUCT_CACHE and time.time() - PRODUCT_CACHE_TS < 3600:
        return PRODUCT_CACHE

    mapping = {}
    per_page = 500
    for ptype in ("products", "batchtickets"):
        page = 1
        while True:
            url = (
                f"https://{ACCOUNT_NAME}.joinposter.com/api/menu.getProducts"
                f"?token={POSTER_TOKEN}&type={ptype}&per_page={per_page}&page={page}"
            )
            try:
                resp = _get(url)
                data = resp.json().get("response", [])
            except Exception as e:
                print("ERROR load_products:", e, file=sys.stderr, flush=True)
                break

            if not isinstance(data, list) or not data:
                break

            for item in data:
                try:
                    pid = int(item.get("product_id", 0))
                    cid = int(item.get("menu_category_id", 0))
                    if pid and cid:
                        mapping[pid] = cid
                except Exception:
                    continue

            if len(data) < per_page:
                break
            page += 1

    PRODUCT_CACHE = mapping
    PRODUCT_CACHE_TS = time.time()
    print(f"DEBUG products cached: {len(PRODUCT_CACHE)} items", file=sys.stderr, flush=True)
    return PRODUCT_CACHE

# ===== Сводные продажи =====
def fetch_category_sales(day_offset=0):
    target_date = (date.today() - timedelta(days=day_offset)).strftime("%Y-%m-%d")
    url = (
        f"https://{ACCOUNT_NAME}.joinposter.com/api/dash.getCategoriesSales"
        f"?token={POSTER_TOKEN}&dateFrom={target_date}&dateTo={target_date}"
    )
    try:
        resp = _get(url)
        rows = resp.json().get("response", [])
    except Exception as e:
        print("ERROR categories:", e, file=sys.stderr, flush=True)
        return {"hot": {}, "cold": {}, "bar": {}}

    hot, cold, bar = {}, {}, {}
    for row in rows:
        try:
            cid = int(row.get("category_id", 0))
            name = row.get("category_name", "").strip()
            qty = int(float(row.get("count", 0)))
        except Exception:
            continue

        if cid in HOT_CATEGORIES:
            hot[name] = hot.get(name, 0) + qty
        elif cid in COLD_CATEGORIES:
            cold[name] = cold.get(name, 0) + qty
        elif cid in BAR_CATEGORIES:
            bar[name] = bar.get(name, 0) + qty

    hot = dict(sorted(hot.items(), key=lambda x: x[0]))
    cold = dict(sorted(cold.items(), key=lambda x: x[0]))
    bar = dict(sorted(bar.items(), key=lambda x: x[0]))
    return {"hot": hot, "cold": cold, "bar": bar}

# ===== Почасовая диаграмма =====
def fetch_transactions_hourly(day_offset=0):
    products = load_products()
    target_date = (date.today() - timedelta(days=day_offset)).strftime("%Y-%m-%d")

    per_page = 500
    page = 1
    hours = list(range(10, 23))
    hot_by_hour = [0] * len(hours)
    cold_by_hour = [0] * len(hours)

    while True:
        url = (
            f"https://{ACCOUNT_NAME}.joinposter.com/api/transactions.getTransactions"
            f"?token={POSTER_TOKEN}&date_from={target_date}&date_to={target_date}"
            f"&per_page={per_page}&page={page}"
        )
        try:
            resp = _get(url)
            body = resp.json().get("response", {})
            items = body.get("data", []) or []
            total = int(body.get("count", 0))
            page_info = body.get("page", {}) or {}
            per_page_resp = int(page_info.get("per_page", per_page) or per_page)
        except Exception as e:
            print("ERROR transactions:", e, file=sys.stderr, flush=True)
            break

        if not items:
            break

        for trx in items:
            dt_str = trx.get("date_close")
            try:
                dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
                hour = dt.hour
                if hour not in hours:
                    continue
                idx = hours.index(hour)
            except Exception:
                continue

            for p in trx.get("products", []) or []:
                try:
                    pid = int(p.get("product_id", 0))
                    qty = int(float(p.get("num", 0)))
                except Exception:
                    continue
                cid = products.get(pid, 0)
                if cid in HOT_CATEGORIES:
                    hot_by_hour[idx] += qty
                elif cid in COLD_CATEGORIES:
                    cold_by_hour[idx] += qty

        if per_page_resp * page >= total:
            break
        page += 1

    hot_cum, cold_cum = [], []
    th, tc = 0, 0
    for h, c in zip(hot_by_hour, cold_by_hour):
        th += h; tc += c
        hot_cum.append(th)
        cold_cum.append(tc)

    labels = [f"{h:02d}:00" for h in hours]
    return {"labels": labels, "hot": hot_cum, "cold": cold_cum}

# ===== Погода =====
def fetch_weather():
    if not WEATHER_KEY:
        return {"temp": "Н/Д", "desc": "Н/Д", "icon": ""}
    try:
        url = f"https://api.openweathermap.org/data/2.5/weather?lat=50.395&lon=30.355&appid={WEATHER_KEY}&units=metric&lang=uk"
        resp = requests.get(url, timeout=10)
        data = resp.json()
        temp = round(data["main"]["temp"])
        desc = data["weather"][0]["description"].capitalize()
        icon = data["weather"][0]["icon"]
        return {"temp": f"{temp}°C", "desc": desc, "icon": icon}
    except Exception as e:
        print("ERROR weather:", e, file=sys.stderr, flush=True)
        return {"temp": "Н/Д", "desc": "Н/Д", "icon": ""}

# ===== Столы =====
HALL_TABLES = [1,2,3,4,5,6,8]
TERRACE_TABLES = [7,10,11,12,13]

def fetch_tables_with_waiters():
    target_date = date.today().strftime("%Y%m%d")
    url = (
        f"https://{ACCOUNT_NAME}.joinposter.com/api/dash.getTransactions"
        f"?token={POSTER_TOKEN}&dateFrom={target_date}&dateTo={target_date}"
    )
    try:
        resp = _get(url)
        rows = resp.json().get("response", [])
    except Exception as e:
        print("ERROR tables_with_waiters:", e, file=sys.stderr, flush=True)
        rows = []

    active = {}
    for trx in rows:
        try:
            status = int(trx.get("status", 0))
            if status == 2:   # закрытые пропускаем
                continue
            tname = int(trx.get("table_name", 0))
            waiter = trx.get("name", "—")
            active[tname] = waiter
        except Exception:
            continue

    # Debug log
    print("DEBUG OPEN TABLES:", active, file=sys.stderr, flush=True)

    def build(zone_numbers):
        out = []
        for tnum in zone_numbers:
            occupied = tnum in active
            waiter = active.get(tnum, "—")
            out.append({
                "id": tnum,
                "name": f"Стол {tnum}",
                "waiter": waiter,
                "occupied": occupied
            })
        return out

    return {"hall": build(HALL_TABLES), "terrace": build(TERRACE_TABLES)}

# ===== API =====
@app.route("/api/sales")
def api_sales():
    global CACHE, CACHE_TS
    if time.time() - CACHE_TS > 60:
        sums_today = fetch_category_sales(0)
        sums_prev = fetch_category_sales(7)
        hourly = fetch_transactions_hourly(0)
        prev = fetch_transactions_hourly(7)

        total_hot = sum(sums_today["hot"].values())
        total_cold = sum(sums_today["cold"].values())
        total_bar = sum(sums_today["bar"].values())
        total_sum = total_hot + total_cold + total_bar
        share = {
            "hot": round(total_hot/total_sum*100) if total_sum else 0,
            "cold": round(total_cold/total_sum*100) if total_sum else 0,
            "bar": round(total_bar/total_sum*100) if total_sum else 0,
        }

        CACHE.update({
            "hot": sums_today["hot"], "cold": sums_today["cold"],
            "hot_prev": sums_prev["hot"], "cold_prev": sums_prev["cold"],
            "hourly": hourly, "hourly_prev": prev,
            "share": share, "weather": fetch_weather(),
            "tables": fetch_tables_with_waiters()
        })
        CACHE_TS = time.time()
    return jsonify(CACHE)

# ===== UI =====
@app.route("/")
def index():
    template = """
    <html>
    <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-datalabels@2"></script>
        <style>
            * {
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }
            
            :root {
                --bg-primary: #1c1c1e;
                --bg-secondary: #2c2c2e;
                --bg-tertiary: #3a3a3c;
                --text-primary: #ffffff;
                --text-secondary: #98989d;
                --accent-hot: #ff6b35;
                --accent-cold: #007aff;
                --accent-bar: #af52de;
                --border-color: rgba(84, 84, 88, 0.65);
                --glass-bg: rgba(44, 44, 46, 0.8);
            }

            body {
                background: var(--bg-primary);
                color: var(--text-primary);
                font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
                height: 100vh;
                overflow: hidden;
                font-size: 14px;
            }

            .dashboard {
                height: 100vh;
                padding: 16px;
                display: grid;
                grid-template-columns: 1fr 1fr 1fr 1fr;
                grid-template-rows: 1fr 1.8fr 1fr;
                gap: 16px;
            }

            .card {
                background: var(--bg-secondary);
                border: 1px solid var(--border-color);
                border-radius: 16px;
                padding: 20px;
                backdrop-filter: blur(20px);
                position: relative;
                overflow: hidden;
                box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
            }

            .card::before {
                content: '';
                position: absolute;
                top: 0;
                left: 0;
                right: 0;
                height: 1px;
                background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.1), transparent);
            }

            .card h2 {
                font-size: 16px;
                font-weight: 600;
                margin-bottom: 16px;
                color: var(--text-primary);
                display: flex;
                align-items: center;
                gap: 8px;
            }

            .card-hot { grid-column: 1; grid-row: 1; }
            .card-cold { grid-column: 2; grid-row: 1; }
            .card-share { grid-column: 3; grid-row: 1; }
            .card-time { grid-column: 4; grid-row: 1; }
            .card-chart { grid-column: 1 / -1; grid-row: 2; }
            .card-hall { grid-column: 1 / 3; grid-row: 3; }
            .card-terrace { grid-column: 3 / 5; grid-row: 3; }

            /* Таблицы */
            table {
                width: 100%;
                border-collapse: collapse;
                font-size: 13px;
            }

            th, td {
                padding: 8px 4px;
                text-align: right;
                border-bottom: 1px solid rgba(84, 84, 88, 0.3);
            }

            th:first-child, td:first-child {
                text-align: left;
            }

            th {
                color: var(--text-secondary);
                font-weight: 500;
                font-size: 12px;
                text-transform: uppercase;
                letter-spacing: 0.5px;
            }

            td {
                color: var(--text-primary);
                font-weight: 500;
            }

            /* Часы и погода */
            .time-display {
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
                height: calc(100% - 50px);
            }

            #clock {
                font-size: 48px;
                font-weight: 700;
                color: var(--text-primary);
                margin-bottom: 16px;
                font-variant-numeric: tabular-nums;
            }

            #weather {
                display: flex;
                align-items: center;
                gap: 8px;
                font-size: 16px;
                color: var(--text-secondary);
                text-align: center;
            }

            /* Диаграммы */
            canvas {
                max-width: 100%;
                max-height: 100%;
            }

            .chart-container {
                height: calc(100% - 50px);
                position: relative;
            }

            /* Столы */
            .tables-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
                gap: 12px;
                height: calc(100% - 50px);
                align-content: start;
            }

            .table-tile {
                background: var(--bg-tertiary);
                border: 1px solid var(--border-color);
                border-radius: 12px;
                padding: 16px;
                text-align: center;
                font-weight: 600;
                font-size: 14px;
                transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
                position: relative;
                overflow: hidden;
            }

            .table-tile.occupied {
                background: linear-gradient(135deg, var(--accent-cold), #0056b3);
                color: white;
                box-shadow: 0 4px 20px rgba(0, 122, 255, 0.3);
            }

            .table-tile.free {
                background: var(--bg-tertiary);
                color: var(--text-secondary);
            }

            .table-name {
                font-size: 16px;
                margin-bottom: 4px;
            }

            .table-waiter {
                font-size: 12px;
                opacity: 0.8;
            }

            /* Логотип */
            .logo {
                position: fixed;
                bottom: 20px;
                right: 24px;
                font-family: 'Inter', sans-serif;
                font-weight: 800;
                font-size: 18px;
                color: var(--text-primary);
                opacity: 0.6;
            }

            /* Эмодзи стили */
            .emoji {
                font-size: 20px;
                margin-right: 4px;
            }

            /* Анимации */
            @keyframes fadeIn {
                from { opacity: 0; transform: translateY(10px); }
                to { opacity: 1; transform: translateY(0); }
            }

            .card {
                animation: fadeIn 0.6s cubic-bezier(0.4, 0, 0.2, 1) forwards;
            }
        </style>
    </head>
    <body>
        <div class="dashboard">
            <div class="card card-hot">
                <h2><span class="emoji">🔥</span>Гарячий цех</h2>
                <table id="hot_tbl"></table>
            </div>

            <div class="card card-cold">
                <h2><span class="emoji">❄️</span>Холодний цех</h2>
                <table id="cold_tbl"></table>
            </div>

            <div class="card card-share">
                <h2><span class="emoji">📊</span>Розподіл замовлень</h2>
                <div class="chart-container">
                    <canvas id="pie"></canvas>
                </div>
            </div>

            <div class="card card-time">
                <h2><span class="emoji">🕐</span>Час і погода</h2>
                <div class="time-display">
                    <div id="clock"></div>
                    <div id="weather"></div>
                </div>
            </div>

            <div class="card card-chart">
                <h2><span class="emoji">📈</span>Замовлення по годинам (накопич.)</h2>
                <div class="chart-container">
                    <canvas id="chart"></canvas>
                </div>
            </div>

            <div class="card card-hall">
                <h2><span class="emoji">🍽️</span>Зал</h2>
                <div id="hall" class="tables-grid"></div>
            </div>

            <div class="card card-terrace">
                <h2><span class="emoji">🌿</span>Літня тераса</h2>
                <div id="terrace" class="tables-grid"></div>
            </div>
        </div>
        
        <div class="logo">GRECO Tech™</div>

        <script>
        let chart, pie;

        function cutToNow(labels, arr){
            const now = new Date();
            const curHour = now.getHours();
            let cutIndex = labels.findIndex(l => parseInt(l) > curHour);
            if(cutIndex === -1) cutIndex = labels.length;
            return arr.slice(0, cutIndex);
        }

        function renderTables(zoneId, data){
            const el = document.getElementById(zoneId);
            el.innerHTML = "";
            data.forEach(t=>{
                const div = document.createElement("div");
                div.className = "table-tile " + (t.occupied ? "occupied":"free");
                div.innerHTML = `
                    <div class="table-name">${t.name}</div>
                    <div class="table-waiter">${t.waiter}</div>
                `;
                el.appendChild(div);
            });
        }

        async function refresh(){
            const r = await fetch('/api/sales');
            const data = await r.json();

            // Таблицы
            function fill(id, today, prev){
                const el = document.getElementById(id);
                let html = "<tr><th>Категорія</th><th>Сьогодні</th><th>Мин. тиждень</th></tr>";
                const keys = new Set([...Object.keys(today), ...Object.keys(prev)]);
                keys.forEach(k => {
                    html += `<tr><td>${k}</td><td>${today[k]||0}</td><td>${prev[k]||0}</td></tr>`;
                });
                el.innerHTML = html;
            }
            fill('hot_tbl', data.hot||{}, data.hot_prev||{});
            fill('cold_tbl', data.cold||{}, data.cold_prev||{});

            // Диаграмма пай с подписями
            Chart.register(ChartDataLabels);
            const ctx2 = document.getElementById('pie').getContext('2d');
            if(pie) pie.destroy();
            pie = new Chart(ctx2,{
                type:'doughnut',
                data:{
                    labels:['Гарячий цех','Холодний цех','Бар'],
                    datasets:[{
                        data:[data.share.hot,data.share.cold,data.share.bar],
                        backgroundColor:['#ff6b35','#007aff','#af52de'],
                        borderWidth: 0,
                        cutout: '50%'
                    }]
                },
                options:{
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins:{
                        legend:{display:false},
                        tooltip:{enabled:false},
                        datalabels:{
                            color:'#ffffff',
                            font:{weight:'bold', size:14, family: 'Inter'},
                            formatter:function(value, context){
                                if(value === 0) return '';
                                const label = context.chart.data.labels[context.dataIndex];
                                return label.split(' ')[0] + '\\n' + value + '%';
                            },
                            textAlign: 'center'
                        }
                    }
                }
            });

            // Линейный график
            let today_hot = cutToNow(data.hourly.labels, data.hourly.hot);
            let today_cold = cutToNow(data.hourly.labels, data.hourly.cold);

            const ctx = document.getElementById('chart').getContext('2d');
            if(chart) chart.destroy();
            chart = new Chart(ctx,{
                type:'line',
                data:{
                    labels:data.hourly.labels,
                    datasets:[
                        {
                            label:'Гарячий',
                            data:today_hot,
                            borderColor:'#ff6b35',
                            backgroundColor:'rgba(255, 107, 53, 0.1)',
                            tension:0.4,
                            fill:false,
                            borderWidth: 3,
                            pointBackgroundColor: '#ff6b35',
                            pointBorderColor: '#ffffff',
                            pointBorderWidth: 2,
                            pointRadius: 4
                        },
                        {
                            label:'Холодний',
                            data:today_cold,
                            borderColor:'#007aff',
                            backgroundColor:'rgba(0, 122, 255, 0.1)',
                            tension:0.4,
                            fill:false,
                            borderWidth: 3,
                            pointBackgroundColor: '#007aff',
                            pointBorderColor: '#ffffff',
                            pointBorderWidth: 2,
                            pointRadius: 4
                        },
                        {
                            label:'Гарячий (мин. тиждень)',
                            data:data.hourly_prev.hot,
                            borderColor:'rgba(255, 107, 53, 0.5)',
                            borderDash:[8,4],
                            tension:0.4,
                            fill:false,
                            borderWidth: 2,
                            pointRadius: 0
                        },
                        {
                            label:'Холодний (мин. тиждень)',
                            data:data.hourly_prev.cold,
                            borderColor:'rgba(0, 122, 255, 0.5)',
                            borderDash:[8,4],
                            tension:0.4,
                            fill:false,
                            borderWidth: 2,
                            pointRadius: 0
                        }
                    ]
                },
                options:{
                    responsive:true,
                    maintainAspectRatio: false,
                    plugins:{
                        legend:{
                            labels:{
                                color:'#98989d',
                                font: {family: 'Inter', size: 12},
                                usePointStyle: true,
                                padding: 20
                            }
                        },
                        datalabels:{display:false}
                    },
                    scales:{
                        x:{
                            ticks:{color:'#98989d', font: {family: 'Inter'}},
                            grid:{color:'rgba(84, 84, 88, 0.3)'},
                            border:{color:'rgba(84, 84, 88, 0.3)'}
                        },
                        y:{
                            ticks:{color:'#98989d', font: {family: 'Inter'}},
                            grid:{color:'rgba(84, 84, 88, 0.3)'},
                            border:{color:'rgba(84, 84, 88, 0.3)'},
                            beginAtZero:true
                        }
                    },
                    elements: {
                        point: {
                            hoverRadius: 6
                        }
                    }
                }
            });

            // Часы и погода
            const now = new Date();
            document.getElementById('clock').innerText = now.toLocaleTimeString('uk-UA',{hour:'2-digit',minute:'2-digit'});
            const w = data.weather||{};
            let whtml = "";
            if(w.icon){ 
                whtml += `<img src="https://openweathermap.org/img/wn/${w.icon}@2x.png" style="width: 32px; height: 32px;">`;
            }
            whtml += `<div>${w.temp||'—'}<br>${w.desc||'—'}</div>`;
            document.getElementById('weather').innerHTML = whtml;

            // Столы
            renderTables('hall', data.tables.hall||[]);
            renderTables('terrace', data.tables.terrace||[]);
        }

        refresh(); 
        setInterval(refresh, 60000);
        </script>
    </body>
    </html>
    """
    return render_template_string(template)

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
