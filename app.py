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

# Категории POS ID
HOT_CATEGORIES  = {4, 13, 15, 46, 33}
COLD_CATEGORIES = {7, 8, 11, 16, 18, 19, 29, 32, 36, 44}

# Фиксированный порядок категорий для горячего цеха
HOT_ORDER = ["Чебуреки", "Янтики", "Піде", "М’ясні страви", "Гарячі страви"]

# Кэш
PRODUCT_CACHE = {}
PRODUCT_CACHE_TS = 0
CACHE = {"hot": {}, "cold": {}, "hot_prev": {}, "cold_prev": {}, "hourly": {}, "hourly_prev": {}}
CACHE_TS = 0

# ===== Helpers =====
def _get(url, **kwargs):
    r = requests.get(url, timeout=kwargs.pop("timeout", 25))
    log_snippet = r.text[:1500].replace("\n", " ")
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
        return {"hot": {}, "cold": {}}

    hot, cold = {}, {}
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

    return {"hot": hot, "cold": cold}

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

# ===== API =====
@app.route("/api/sales")
def api_sales():
    global CACHE, CACHE_TS
    if time.time() - CACHE_TS > 60:
        today = fetch_category_sales(0)
        prev = fetch_category_sales(7)
        hourly = fetch_transactions_hourly(0)
        prev_hourly = fetch_transactions_hourly(7)
        CACHE.update({
            "hot": today["hot"], "cold": today["cold"],
            "hot_prev": prev["hot"], "cold_prev": prev["cold"],
            "hourly": hourly, "hourly_prev": prev_hourly
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
        <style>
            :root {
                --bg:#0f0f0f; --panel:#151515; --fg:#eee;
                --hot:#ff8800; --cold:#33b5ff;
            }
            body{margin:0;background:var(--bg);color:var(--fg);font-family:Inter,Arial,sans-serif}
            .wrap{padding:10px;max-width:1600px;margin:0 auto}
            .row{display:grid;grid-template-columns:repeat(2,1fr);gap:10px}
            .card{background:var(--panel);border-radius:10px;padding:10px 12px;}
            .card.chart{grid-column:1/-1;}
            table{width:100%;border-collapse:collapse;font-size:16px}
            th,td{padding:4px 6px;text-align:right}
            th:first-child, td:first-child{text-align:left}
            td.today{color:#fff;font-weight:700}
            td.prev{color:#888;font-weight:400}
            .logo{position:fixed;right:12px;bottom:8px;font-weight:800}
        </style>
    </head>
    <body>
        <div class="wrap">
            <div class="row">
                <div class="card hot"><h2>🔥 Гарячий цех</h2>
                    <table id="hot_tbl"><thead><tr><th>Категорія</th><th>Сьогодні</th><th>Мин. тижд.</th></tr></thead><tbody></tbody></table>
                </div>
                <div class="card cold"><h2>❄️ Холодний цех</h2>
                    <table id="cold_tbl"><thead><tr><th>Категорія</th><th>Сьогодні</th><th>Мин. тижд.</th></tr></thead><tbody></tbody></table>
                </div>
                <div class="card chart"><h2>📊 Замовлення по годинах (накопич.)</h2><canvas id="chart" height="140"></canvas></div>
            </div>
        </div>
        <div class="logo">GRECO Tech ™</div>

        <script>
        let chart;
        const HOT_ORDER = ["Чебуреки","Янтики","Піде","М’ясні страви","Гарячі страви"];

        function cutToNow(labels, arrHot, arrCold){
            const now = new Date();
            const curHour = now.getHours();
            let cutIndex = labels.findIndex(l => parseInt(l) > curHour);
            if(cutIndex === -1) cutIndex = labels.length;
            return {
                labels: labels.slice(0, cutIndex),
                hot: arrHot.slice(0, cutIndex),
                cold: arrCold.slice(0, cutIndex)
            }
        }

        async function refresh(){
            const r = await fetch('/api/sales');
            const data = await r.json();

            function fillHot(){
                const tbody = document.querySelector('#hot_tbl tbody');
                let html = "";
                HOT_ORDER.forEach(cat => {
                    const today = data.hot[cat] || 0;
                    const prev = data.hot_prev[cat] || 0;
                    html += `<tr><td>${cat}</td><td class="today">${today}</td><td class="prev">${prev}</td></tr>`;
                });
                tbody.innerHTML = html;
            }

            function fillCold(){
                const tbody = document.querySelector('#cold_tbl tbody');
                let html = "";
                const allCats = new Set([...Object.keys(data.cold||{}), ...Object.keys(data.cold_prev||{})]);
                Array.from(allCats).sort().forEach(cat => {
                    const today = data.cold[cat] || 0;
                    const prev = data.cold_prev[cat] || 0;
                    html += `<tr><td>${cat}</td><td class="today">${today}</td><td class="prev">${prev}</td></tr>`;
                });
                tbody.innerHTML = html;
            }

            fillHot();
            fillCold();

            let today = cutToNow(data.hourly.labels, data.hourly.hot, data.hourly.cold);
            let prev = {
                labels: data.hourly_prev.labels,
                hot: data.hourly_prev.hot,
                cold: data.hourly_prev.cold
            };

            const ctx = document.getElementById('chart').getContext('2d');
            if(chart) chart.destroy();
            chart = new Chart(ctx,{
                type:'line',
                data:{
                    labels: data.hourly.labels,
                    datasets:[
                        {label:'Гарячий', data:today.hot, borderColor:'#ff8800', backgroundColor:'#ff8800', tension:0.25, fill:false},
                        {label:'Холодний', data:today.cold, borderColor:'#33b5ff', backgroundColor:'#33b5ff', tension:0.25, fill:false},
                        {label:'Гарячий (мин. тижд.)', data:prev.hot, borderColor:'#ff8800', borderDash:[6,4], tension:0.25, fill:false},
                        {label:'Холодний (мин. тижд.)', data:prev.cold, borderColor:'#33b5ff', borderDash:[6,4], tension:0.25, fill:false}
                    ]
                },
                options:{
                    responsive:true,
                    plugins:{legend:{labels:{color:'#ddd'}}},
                    scales:{
                        x:{ticks:{color:'#bbb'}, min:'10:00', max:'22:00'},
                        y:{ticks:{color:'#bbb'}, beginAtZero:true}
                    }
                }
            });
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
