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
CACHE = {"hot": {}, "cold": {}, "hot_prev": {}, "cold_prev": {}, "hourly": {}, "hourly_prev": {}, "share": {}}
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
            "share": share, "weather": fetch_weather()
        })
        CACHE_TS = time.time()
    return jsonify(CACHE)

# ===== UI =====
@app.route("/")
def index():
    template = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Kitchen Dashboard - GRECO</title>
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <style>
            :root {
                --bg: #0a0a0a;
                --panel: #1a1a1a;
                --panel-alt: #252525;
                --fg: #ffffff;
                --fg-secondary: #cccccc;
                --hot: #ff6b35;
                --cold: #00d4ff;
                --bar: #a855f7;
                --accent: #10b981;
                --border: #333333;
            }
            
            * {
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }
            
            body {
                background: var(--bg);
                color: var(--fg);
                font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, sans-serif;
                height: 100vh;
                overflow: hidden;
                font-size: 14px;
            }
            
            .dashboard {
                height: 100vh;
                display: grid;
                grid-template-columns: 1fr 1fr 1fr 1fr;
                grid-template-rows: 1fr 1fr;
                gap: 8px;
                padding: 8px;
            }
            
            .card {
                background: linear-gradient(135deg, var(--panel) 0%, var(--panel-alt) 100%);
                border: 1px solid var(--border);
                border-radius: 16px;
                padding: 12px;
                display: flex;
                flex-direction: column;
                position: relative;
                overflow: hidden;
                backdrop-filter: blur(10px);
                box-shadow: 0 8px 32px rgba(0,0,0,0.3);
            }
            
            .card::before {
                content: '';
                position: absolute;
                top: 0;
                left: 0;
                right: 0;
                height: 2px;
                background: linear-gradient(90deg, var(--hot), var(--cold), var(--bar));
                opacity: 0.6;
            }
            
            .card h2 {
                font-size: 16px;
                font-weight: 600;
                margin-bottom: 8px;
                color: var(--fg);
                display: flex;
                align-items: center;
                gap: 6px;
            }
            
            .card-content {
                flex: 1;
                display: flex;
                flex-direction: column;
                min-height: 0;
            }
            
            /* Таблицы */
            table {
                width: 100%;
                border-collapse: collapse;
                font-size: 12px;
                flex: 1;
            }
            
            th {
                background: var(--panel-alt);
                color: var(--fg);
                font-weight: 600;
                padding: 6px 8px;
                text-align: left;
                border-radius: 6px;
                font-size: 11px;
            }
            
            td {
                padding: 4px 8px;
                border-bottom: 1px solid var(--border);
                color: var(--fg-secondary);
            }
            
            th:nth-child(2), td:nth-child(2),
            th:nth-child(3), td:nth-child(3) {
                text-align: right;
                width: 60px;
            }
            
            tr:hover td {
                background: var(--panel-alt);
                color: var(--fg);
            }
            
            /* График */
            .chart-card {
                grid-column: 1 / -1;
                grid-row: 2;
            }
            
            .chart-container {
                flex: 1;
                position: relative;
                min-height: 0;
            }
            
            canvas {
                max-width: 100% !important;
                max-height: 100% !important;
            }
            
            /* Круговая диаграмма */
            .pie-card {
                display: flex;
                flex-direction: column;
                align-items: center;
            }
            
            .pie-container {
                flex: 1;
                display: flex;
                align-items: center;
                justify-content: center;
                position: relative;
                max-height: 200px;
                width: 100%;
            }
            
            /* Время и погода */
            .weather-card {
                text-align: center;
            }
            
            .clock {
                font-size: 36px;
                font-weight: 700;
                color: var(--accent);
                margin: 12px 0;
                font-variant-numeric: tabular-nums;
                width: 80%;
                text-align: center;
                margin-left: auto;
                margin-right: auto;
            }
            
            .weather {
                display: flex;
                flex-direction: column;
                align-items: center;
                gap: 8px;
                flex: 1;
                justify-content: center;
                width: 80%;
                margin: 0 auto;
            }
            
            .weather img {
                width: 80px;
                height: 80px;
                filter: drop-shadow(0 2px 4px rgba(0,0,0,0.3));
            }
            
            .temp {
                font-size: 24px;
                font-weight: 600;
                color: var(--fg);
            }
            
            .desc {
                font-size: 14px;
                color: var(--fg-secondary);
                text-transform: capitalize;
                text-align: center;
            }
            
            /* Лого */
            .logo {
                position: fixed;
                bottom: 12px;
                right: 16px;
                font-weight: 800;
                font-size: 18px;
                color: var(--accent);
                text-shadow: 0 2px 4px rgba(0,0,0,0.5);
                z-index: 1000;
            }
            
            /* Статистика в шапке карточек */
            .stat-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 8px;
            }
            
            .stat-number {
                font-size: 20px;
                font-weight: 700;
                color: var(--accent);
            }
            
            /* Адаптация под очень маленькие экраны */
            @media (max-height: 600px) {
                .dashboard {
                    gap: 4px;
                    padding: 4px;
                }
                
                .card {
                    padding: 8px;
                    border-radius: 12px;
                }
                
                .card h2 {
                    font-size: 14px;
                    margin-bottom: 6px;
                }
                
                table {
                    font-size: 11px;
                }
                
                th, td {
                    padding: 3px 6px;
                }
                
                .clock {
                    font-size: 24px;
                    margin: 4px 0;
                }
            }
            
            /* Scrollbar для таблиц если нужно */
            .table-container {
                flex: 1;
                overflow-y: auto;
                overflow-x: hidden;
            }
            
            .table-container::-webkit-scrollbar {
                width: 4px;
            }
            
            .table-container::-webkit-scrollbar-track {
                background: var(--panel);
            }
            
            .table-container::-webkit-scrollbar-thumb {
                background: var(--border);
                border-radius: 2px;
            }
        </style>
    </head>
    <body>
        <div class="dashboard">
            <!-- Горячий цех -->
            <div class="card">
                <div class="stat-header">
                    <h2>🔥 Гарячий цех</h2>
                    <span class="stat-number" id="hot-total">0</span>
                </div>
                <div class="table-container">
                    <table id="hot_tbl"></table>
                </div>
            </div>
            
            <!-- Холодный цех -->
            <div class="card">
                <div class="stat-header">
                    <h2>❄️ Холодний цех</h2>
                    <span class="stat-number" id="cold-total">0</span>
                </div>
                <div class="table-container">
                    <table id="cold_tbl"></table>
                </div>
            </div>
            
            <!-- Круговая диаграмма -->
            <div class="card pie-card">
                <h2>📊 Розподіл замовлень</h2>
                <div class="pie-container">
                    <canvas id="pie" width="180" height="180"></canvas>
                </div>
            </div>
            
            <!-- Время и погода -->
            <div class="card weather-card">
                <h2>🕐 Час і погода</h2>
                <div class="card-content">
                    <div class="clock" id="clock">00:00</div>
                    <div class="weather" id="weather">
                        <div class="temp">—°C</div>
                        <div class="desc">Завантаження...</div>
                    </div>
                </div>
            </div>
            
            <!-- График заказов по часам -->
            <div class="card chart-card">
                <h2>📈 Замовлення по годинах (накопич.)</h2>
                <div class="chart-container">
                    <canvas id="chart"></canvas>
                </div>
            </div>
        </div>
        
        <div class="logo">GRECO</div>

        <script>
        let chart, pie;

        function cutToNow(labels, arr) {
            const now = new Date();
            const curHour = now.getHours();
            let cutIndex = labels.findIndex(l => parseInt(l) > curHour);
            if(cutIndex === -1) cutIndex = labels.length;
            return arr.slice(0, cutIndex);
        }

        async function refresh() {
            try {
                const r = await fetch('/api/sales');
                const data = await r.json();

                // Обновление таблиц с подсчетом общих сумм
                function fill(id, today, prev, totalId) {
                    const el = document.getElementById(id);
                    const totalEl = document.getElementById(totalId);
                    
                    let html = "<tr><th>Категорія</th><th>Сьогодні</th><th>Мин. тиждень</th></tr>";
                    const keys = new Set([...Object.keys(today), ...Object.keys(prev)]);
                    
                    let total = 0;
                    keys.forEach(k => {
                        const todayVal = today[k] || 0;
                        const prevVal = prev[k] || 0;
                        total += todayVal;
                        html += `<tr><td>${k}</td><td>${todayVal}</td><td>${prevVal}</td></tr>`;
                    });
                    
                    el.innerHTML = html;
                    totalEl.textContent = total;
                }
                
                fill('hot_tbl', data.hot || {}, data.hot_prev || {}, 'hot-total');
                fill('cold_tbl', data.cold || {}, data.cold_prev || {}, 'cold-total');

                // Круговая диаграмма
                const ctx2 = document.getElementById('pie').getContext('2d');
                if(pie) pie.destroy();
                
                pie = new Chart(ctx2, {
                    type: 'pie',
                    data: {
                        labels: ['Гарячий', 'Холодний', 'Бар'],
                        datasets: [{
                            data: [data.share.hot, data.share.cold, data.share.bar],
                            backgroundColor: ['#ff6b35', '#00d4ff', '#a855f7'],
                            borderColor: '#1a1a1a',
                            borderWidth: 2
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {
                            legend: {
                                display: false
                            },
                            tooltip: {
                                backgroundColor: 'rgba(26, 26, 26, 0.9)',
                                titleColor: '#ffffff',
                                bodyColor: '#cccccc',
                                borderColor: '#333333',
                                borderWidth: 1,
                                callbacks: {
                                    label: function(context) {
                                        return context.label + ': ' + context.parsed + '%';
                                    }
                                }
                            },
                            datalabels: {
                                display: true,
                                color: '#ffffff',
                                font: {
                                    weight: 'bold',
                                    size: 12
                                },
                                formatter: function(value, context) {
                                    if (value > 5) { // Показывать только если процент больше 5%
                                        const label = context.chart.data.labels[context.dataIndex];
                                        return label + '\n' + value + '%';
                                    }
                                    return '';
                                }
                            }
                        }
                    },
                    plugins: [{
                        id: 'centerLabels',
                        afterDraw: function(chart) {
                            const ctx = chart.ctx;
                            const chartArea = chart.chartArea;
                            
                            chart.data.datasets.forEach((dataset, i) => {
                                const meta = chart.getDatasetMeta(i);
                                meta.data.forEach((element, index) => {
                                    if (dataset.data[index] > 5) { // Показываем только если больше 5%
                                        const position = element.tooltipPosition();
                                        const label = chart.data.labels[index];
                                        const value = dataset.data[index];
                                        
                                        ctx.fillStyle = '#ffffff';
                                        ctx.font = 'bold 11px Arial';
                                        ctx.textAlign = 'center';
                                        ctx.textBaseline = 'middle';
                                        
                                        const lines = [label, value + '%'];
                                        lines.forEach((line, lineIndex) => {
                                            ctx.fillText(line, position.x, position.y + (lineIndex - 0.5) * 12);
                                        });
                                    }
                                });
                            });
                        }
                    }]
                });

                // Линейная диаграмма
                let today_hot = cutToNow(data.hourly.labels, data.hourly.hot);
                let today_cold = cutToNow(data.hourly.labels, data.hourly.cold);

                const ctx = document.getElementById('chart').getContext('2d');
                if(chart) chart.destroy();
                
                chart = new Chart(ctx, {
                    type: 'line',
                    data: {
                        labels: data.hourly.labels,
                        datasets: [
                            {
                                label: 'Гарячий',
                                data: today_hot,
                                borderColor: '#ff6b35',
                                backgroundColor: 'rgba(255, 107, 53, 0.1)',
                                tension: 0.4,
                                fill: false,
                                pointRadius: 3,
                                pointHoverRadius: 5,
                                borderWidth: 2
                            },
                            {
                                label: 'Холодний',
                                data: today_cold,
                                borderColor: '#00d4ff',
                                backgroundColor: 'rgba(0, 212, 255, 0.1)',
                                tension: 0.4,
                                fill: false,
                                pointRadius: 3,
                                pointHoverRadius: 5,
                                borderWidth: 2
                            },
                            {
                                label: 'Гарячий (мин. тиждень)',
                                data: data.hourly_prev.hot,
                                borderColor: '#ff6b35',
                                borderDash: [6, 4],
                                tension: 0.4,
                                fill: false,
                                pointRadius: 2,
                                borderWidth: 1,
                                pointStyle: 'circle'
                            },
                            {
                                label: 'Холодний (мин. тиждень)',
                                data: data.hourly_prev.cold,
                                borderColor: '#00d4ff',
                                borderDash: [6, 4],
                                tension: 0.4,
                                fill: false,
                                pointRadius: 2,
                                borderWidth: 1,
                                pointStyle: 'circle'
                            }
                        ]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        interaction: {
                            intersect: false,
                            mode: 'index'
                        },
                        plugins: {
                            legend: {
                                labels: {
                                    color: '#cccccc',
                                    font: {
                                        size: 11
                                    },
                                    usePointStyle: true,
                                    padding: 15
                                }
                            },
                            tooltip: {
                                backgroundColor: 'rgba(26, 26, 26, 0.9)',
                                titleColor: '#ffffff',
                                bodyColor: '#cccccc',
                                borderColor: '#333333',
                                borderWidth: 1
                            }
                        },
                        scales: {
                            x: {
                                ticks: {
                                    color: '#cccccc',
                                    font: {
                                        size: 10
                                    }
                                },
                                grid: {
                                    color: '#333333',
                                    lineWidth: 0.5
                                },
                                title: {
                                    display: true,
                                    text: 'Година',
                                    color: '#cccccc',
                                    font: {
                                        size: 11
                                    }
                                }
                            },
                            y: {
                                ticks: {
                                    color: '#cccccc',
                                    font: {
                                        size: 10
                                    }
                                },
                                grid: {
                                    color: '#333333',
                                    lineWidth: 0.5
                                },
                                beginAtZero: true
                            }
                        }
                    }
                });

                // Часы и погода
                const now = new Date();
                document.getElementById('clock').textContent = now.toLocaleTimeString('uk-UA', {
                    hour: '2-digit',
                    minute: '2-digit'
                });

                const w = data.weather || {};
                const weatherEl = document.getElementById('weather');
                
                let whtml = `<div class="temp">${w.temp || '—'}</div>`;
                if (w.icon) {
                    whtml = `<img src="https://openweathermap.org/img/wn/${w.icon}@2x.png" alt="weather"> ` + whtml;
                }
                whtml += `<div class="desc">${w.desc || '—'}</div>`;
                
                weatherEl.innerHTML = whtml;
                
            } catch (error) {
                console.error('Error refreshing data:', error);
            }
        }

        // Инициализация и автообновление
        refresh();
        setInterval(refresh, 60000);
        
        // Обновление часов каждую секунду
        setInterval(() => {
            const now = new Date();
            document.getElementById('clock').textContent = now.toLocaleTimeString('uk-UA', {
                hour: '2-digit',
                minute: '2-digit'
            });
        }, 1000);
        </script>
    </body>
    </html>
    """
    return render_template_string(template)

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
