import os
import time
import requests
import sys
from datetime import date, datetime, timedelta
from flask import Flask, render_template_string, jsonify

app = Flask(__name__)

# ==== Конфиг ====
ACCOUNT_NAME = "poka-net3"
POSTER_TOKEN = os.getenv("POSTER_TOKEN")  # обязателен

# Категории POS ID (по menu_category_id)
HOT_CATEGORIES = {4, 13, 15, 46, 33}
COLD_CATEGORIES = {7, 8, 11, 16, 18, 19, 29, 32, 36, 44}

# Кэш
PRODUCT_CACHE = {}            # product_id -> menu_category_id
PRODUCT_CACHE_TS = 0
CACHE = {"hot": {}, "cold": {}, "hot_prev": {}, "cold_prev": {}, "hourly": {}, "hourly_prev": {}}
CACHE_TS = 0

# ===== Helpers =====
def _get(url, **kwargs):
    r = requests.get(url, timeout=kwargs.pop("timeout", 25))
    log_snippet = r.text[:500].replace("\n", " ")
    print(f"DEBUG GET {url.split('?')[0]} -> {r.status_code} : {log_snippet}", file=sys.stderr, flush=True)
    r.raise_for_status()
    return r

def load_products():
    """Кэшируем соответствие product_id -> menu_category_id (на 1 час)."""
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

def fetch_category_names():
    """
    Берём имена категорий (id -> name) с dash.getCategoriesSales за сегодня.
    """
    today = date.today().strftime("%Y-%m-%d")
    url = (
        f"https://{ACCOUNT_NAME}.joinposter.com/api/dash.getCategoriesSales"
        f"?token={POSTER_TOKEN}&dateFrom={today}&dateTo={today}"
    )
    out = {}
    try:
        resp = _get(url)
        rows = resp.json().get("response", []) or []
        for row in rows:
            try:
                cid = int(row.get("category_id", 0))
                name = (row.get("category_name") or "").strip()
                if cid and name:
                    out[cid] = name
            except Exception:
                continue
    except Exception as e:
        print("ERROR fetch_category_names:", e, file=sys.stderr, flush=True)
    return out

def aggregate_categories_until(day_offset=0, until_hour=None):
    """
    Суммирует количество блюд по категориям ДО указанного часа (включительно).
    Возвращает два словаря:
      hot: {category_id: qty}, cold: {category_id: qty}
    """
    products = load_products()
    target_date = (date.today() - timedelta(days=day_offset)).strftime("%Y-%m-%d")
    if until_hour is None:
        until_hour = datetime.now().hour

    per_page = 500
    page = 1
    hot = {}
    cold = {}

    while True:
        url = (
            f"https://{ACCOUNT_NAME}.joinposter.com/api/transactions.getTransactions"
            f"?token={POSTER_TOKEN}&date_from={target_date}&date_to={target_date}"
            f"&per_page={per_page}&page={page}"
        )
        try:
            resp = _get(url)
            body = resp.json().get("response", {}) or {}
            items = body.get("data", []) or []
            total = int(body.get("count", 0) or 0)
            page_info = body.get("page", {}) or {}
            per_page_resp = int(page_info.get("per_page", per_page) or per_page)
        except Exception as e:
            print("ERROR aggregate_categories_until:", e, file=sys.stderr, flush=True)
            break

        if not items:
            break

        for trx in items:
            dt_str = trx.get("date_close")
            try:
                dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
                hour = dt.hour
                if hour > until_hour:
                    continue
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
                    hot[cid] = hot.get(cid, 0) + qty
                elif cid in COLD_CATEGORIES:
                    cold[cid] = cold.get(cid, 0) + qty

        if per_page_resp * page >= total:
            break
        page += 1

    return hot, cold

def fetch_transactions_hourly(day_offset=0):
    """Кумулятив по часам для графика."""
    products = load_products()
    target_date = (date.today() - timedelta(days=day_offset)).strftime("%Y-%m-%d")

    per_page = 500
    page = 1
    hours = list(range(10, 23))   # 10:00–22:00
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
            body = resp.json().get("response", {}) or {}
            items = body.get("data", []) or []
            total = int(body.get("count", 0) or 0)
            page_info = body.get("page", {}) or {}
            per_page_resp = int(page_info.get("per_page", per_page) or per_page)
        except Exception as e:
            print("ERROR fetch_transactions_hourly:", e, file=sys.stderr, flush=True)
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
        hot_cum.append(th); cold_cum.append(tc)

    labels = [f"{h:02d}:00" for h in hours]
    return {"labels": labels, "hot": hot_cum, "cold": cold_cum}

# ===== API =====
@app.route("/api/sales")
def api_sales():
    global CACHE, CACHE_TS
    if time.time() - CACHE_TS > 60:
        now_hour = datetime.now().hour

        cat_names = fetch_category_names()

        # таблицы
        hot_today, cold_today = aggregate_categories_until(0, now_hour)
        hot_prev, cold_prev = aggregate_categories_until(7, now_hour)

        def ensure_all(categories, today_dict, prev_dict):
            out_today, out_prev = {}, {}
            for cid in categories:
                name = cat_names.get(cid, f"Категорія {cid}")
                out_today[name] = today_dict.get(cid, 0)
                out_prev[name] = prev_dict.get(cid, 0)
            return out_today, out_prev

        hot_today_n, hot_prev_n = ensure_all(HOT_CATEGORIES, hot_today, hot_prev)
        cold_today_n, cold_prev_n = ensure_all(COLD_CATEGORIES, cold_today, cold_prev)

        hourly_today = fetch_transactions_hourly(0)
        hourly_prev = fetch_transactions_hourly(7)

        CACHE.update({
            "hot": hot_today_n,
            "cold": cold_today_n,
            "hot_prev": hot_prev_n,
            "cold_prev": cold_prev_n,
            "hourly": hourly_today,
            "hourly_prev": hourly_prev
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
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <style>
            body{margin:0;background:#0f0f0f;color:#eee;font-family:Inter,Arial,sans-serif}
            .wrap{height:100vh;max-width:1920px;margin:0 auto;padding:10px;display:grid;grid-template-rows:auto 1fr;gap:10px}
            .top{display:grid;grid-template-columns:1fr 1fr;gap:10px}
            .card{background:#151515;border-radius:10px;padding:10px}
            h2{font-size:18px;margin:0 0 6px 0}
            table{width:100%;border-collapse:collapse;font-size:16px}
            th,td{padding:3px 6px;text-align:right}
            th:first-child,td:first-child{text-align:left}
            td.today{font-weight:800;color:#fff}
            td.prev{color:#8a8f98;font-weight:600}
            .chart-card{display:flex;flex-direction:column}
            .chart-wrap{flex:1}
            canvas{width:100%;height:100%}
            .logo{position:fixed;right:12px;bottom:8px;font-weight:800;font-size:14px}
        </style>
    </head>
    <body>
        <div class="wrap">
            <div class="top">
                <div class="card">
                    <h2>🔥 Гарячий цех</h2>
                    <table id="hot_tbl"><thead><tr><th>Категорія</th><th>Сьогодні</th><th>Мин. тиждень</th></tr></thead><tbody></tbody></table>
                </div>
                <div class="card">
                    <h2>❄️ Холодний цех</h2>
                    <table id="cold_tbl"><thead><tr><th>Категорія</th><th>Сьогодні</th><th>Мин. тиждень</th></tr></thead><tbody></tbody></table>
                </div>
            </div>
            <div class="card chart-card">
                <h2>📊 Замовлення по годинах (накопич.)</h2>
                <div class="chart-wrap"><canvas id="chart"></canvas></div>
            </div>
        </div>
        <div class="logo">GRECO Tech ™</div>

        <script>
        let chart;
        function cutToNow(labels, hot, cold){
            const now=new Date();const h=now.getHours();
            let idx=labels.findIndex(l=>parseInt(l)>h);
            if(idx===-1) idx=labels.length;
            return {labels:labels.slice(0,idx),hot:hot.slice(0,idx),cold:cold.slice(0,idx)};
        }
        async function refresh(){
            const r=await fetch('/api/sales');const d=await r.json();
            function fill(id,today,prev){
                const tb=document.querySelector("#"+id+" tbody");
                let html="";
                Object.keys(today).forEach(cat=>{
                    html+=`<tr><td>${cat}</td><td class="today">${today[cat]}</td><td class="prev">${prev[cat]}</td></tr>`;
                });
                tb.innerHTML=html;
            }
            fill('hot_tbl',d.hot,d.hot_prev); fill('cold_tbl',d.cold,d.cold_prev);

            const today=cutToNow(d.hourly.labels,d.hourly.hot,d.hourly.cold);
            const prev={labels:d.hourly_prev.labels,hot:d.hourly_prev.hot,cold:d.hourly_prev.cold};

            const ctx=document.getElementById('chart').getContext('2d');
            if(chart) chart.destroy();
            chart=new Chart(ctx,{type:'line',data:{labels:d.hourly.labels,datasets:[
                {label:'Гарячий',data:today.hot,borderColor:'#ff8800',tension:0.25,fill:false},
                {label:'Холодний',data:today.cold,borderColor:'#33b5ff',tension:0.25,fill:false},
                {label:'Гарячий (мин. тижд.)',data:prev.hot,borderColor:'#ff8800',borderDash:[6,4],tension:0.25,fill:false},
                {label:'Холодний (мин. тижд.)',data:prev.cold,borderColor:'#33b5ff',borderDash:[6,4],tension:0.25,fill:false}
            ]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{labels:{color:'#ddd'}}},scales:{x:{ticks:{color:'#bbb'}},y:{ticks:{color:'#bbb'},beginAtZero:true}}}});
        }
        refresh(); setInterval(refresh,60000);
        </script>
    </body>
    </html>
    """
    return render_template_string(template)

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
