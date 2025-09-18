import os
import time
import requests
import sys
from datetime import date, datetime, timedelta
from flask import Flask, render_template_string, jsonify

app = Flask(__name__)

# ==== Конфиг ====
ACCOUNT_NAME = os.getenv("ACCOUNT_NAME", "poka-net3")
POSTER_TOKEN = os.getenv("POSTER_TOKEN")
CHOICE_TOKEN = os.getenv("CHOICE_TOKEN")
WEATHER_KEY = os.getenv("WEATHER_KEY", "")

# Категории POS ID
HOT_CATEGORIES  = {4, 13, 15, 46, 33}
COLD_CATEGORIES = {7, 8, 11, 16, 18, 19, 29, 32, 36, 44}
BAR_CATEGORIES  = {9,14,27,28,34,41,42,47,22,24,25,26,39,30}

# Кэш
PRODUCT_CACHE = {}
PRODUCT_CACHE_TS = 0
CACHE = {"hot": {}, "cold": {}, "bar": {}, "hot_prev": {}, "cold_prev": {}, "hourly": {}, "hourly_prev": {}, "share": {}}
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
            "hot": sums_today["hot"], "cold": sums_today["cold"], "bar": sums_today["bar"],
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
    <html>
    <head>
        <meta charset="utf-8" />
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-datalabels@2"></script>
        <style>
            :root {
                --bg:#0f0f0f; --panel:#151515; --fg:#eee;
                --hot:#ff8800; --cold:#33b5ff; --bar:#9b59b6;
            }
            body{margin:0;background:var(--bg);color:var(--fg);font-family:Inter,Arial,sans-serif;overflow:hidden}
            .wrap{padding:10px;max-width:1920px;margin:0 auto;height:100vh;display:flex;flex-direction:column}
            .top{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;flex:0 0 40%}
            .bottom{flex:1;margin-top:10px}
            .card{background:var(--panel);border-radius:12px;padding:10px 14px;height:100%}
            table{width:100%;border-collapse:collapse;font-size:18px}
            th,td{padding:3px 6px;text-align:right}
            th:first-child,td:first-child{text-align:left}
            .logo{position:fixed;right:18px;bottom:12px;font-weight:800}
        </style>
    </head>
    <body>
        <div class="wrap">
            <div class="top">
                <div class="card"><h2>🔥 Гарячий цех</h2><table id="hot_tbl"></table></div>
                <div class="card"><h2>❄️ Холодний цех</h2><table id="cold_tbl"></table></div>
                <div class="card"><h2>📊 Розподіл замовлень</h2><canvas id="pie"></canvas></div>
                <div class="card"><h2>🕒 Час і погода</h2>
                    <div id="clock" style="font-size:64px;margin-top:10px"></div>
                    <div id="weather" style="margin-top:10px;font-size:22px"></div>
                </div>
            </div>
            <div class="bottom card">
                <h2>📈 Замовлення по годинах (накопич.)</h2><canvas id="chart" style="height:100%"></canvas>
            </div>
        </div>
        <div class="logo">GRECO</div>

        <script>
        let chart, pie;

        function cutToNow(labels, arr){
            const now = new Date();
            const curHour = now.getHours();
            let cutIndex = labels.findIndex(l => parseInt(l) > curHour);
            if(cutIndex === -1) cutIndex = labels.length;
            return arr.slice(0, cutIndex);
        }

        async function refresh(){
            const r = await fetch('/api/sales');
            const data = await r.json();

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

            // Круговая диаграмма (без легенды, подписи внутри)
            const ctx2 = document.getElementById('pie').getContext('2d');
            if(pie) pie.destroy();
            pie = new Chart(ctx2,{
                type:'pie',
                data:{
                    labels:['Бар','Гор. цех','Хол. цех'],
                    datasets:[{
                        data:[data.share.bar,data.share.hot,data.share.cold],
                        backgroundColor:['#9b59b6','#ff8800','#33b5ff']
                    }]
                },
                options:{
                    plugins:{
                        legend:{display:false},
                        datalabels:{
                            color:'#fff',
                            font:{weight:'bold',size:18},
                            formatter:(val,ctx)=>{
                                let label = ctx.chart.data.labels[ctx.dataIndex];
                                return label + "\\n" + val + '%';
                            }
                        }
                    }
                },
                plugins:[ChartDataLabels]
            });

            // Линейная диаграмма
            let today_hot = cutToNow(data.hourly.labels, data.hourly.hot);
            let today_cold = cutToNow(data.hourly.labels, data.hourly.cold);

            const ctx = document.getElementById('chart').getContext('2d');
            if(chart) chart.destroy();
            chart = new Chart(ctx,{
                type:'line',
                data:{
                    labels:data.hourly.labels,
                    datasets:[
                        {label:'Гарячий',data:today_hot,borderColor:'#ff8800',backgroundColor:'#ff8800',tension:0.25,fill:false},
                        {label:'Холодний',data:today_cold,borderColor:'#33b5ff',backgroundColor:'#33b5ff',tension:0.25,fill:false},
                        {label:'Гарячий (мин. тижд.)',data:data.hourly_prev.hot,borderColor:'#ff8800',borderDash:[6,4],tension:0.25,fill:false},
                        {label:'Холодний (мин. тижд.)',data:data.hourly_prev.cold,borderColor:'#33b5ff',borderDash:[6,4],tension:0.25,fill:false}
                    ]
                },
                options:{
                    responsive:true,
                    maintainAspectRatio:false,
                    plugins:{legend:{labels:{color:'#ddd'}}},
                    scales:{
                        x:{ticks:{color:'#bbb'},title:{display:true,text:'Час'}},
                        y:{ticks:{color:'#bbb'},beginAtZero:true}
                    }
                }
            });

            // Часы и погода
            const now = new Date();
            document.getElementById('clock').innerText = now.toLocaleTimeString('uk-UA',{hour:'2-digit',minute:'2-digit'});
            const w = data.weather||{};
            let whtml = "";
            if(w.icon){ whtml += `<img src="https://openweathermap.org/img/wn/${w.icon}@2x.png" style="vertical-align:middle">`; }
            whtml += ` ${w.temp||'—'}<br>${w.desc||'—'}`;
            document.getElementById('weather').innerHTML = whtml;
        }
        refresh(); setInterval(refresh, 60000);
        </script>
    </body>
    </html>
    """
    return render_template_string(template)

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
