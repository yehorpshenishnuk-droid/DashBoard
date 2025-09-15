import os
import time
import math
import requests
import sys
from datetime import date, datetime
from flask import Flask, render_template_string, jsonify

app = Flask(__name__)

# ==== Конфиг ====
ACCOUNT_NAME = "poka-net3"
POSTER_TOKEN = os.getenv("POSTER_TOKEN")           # обязателен
CHOICE_TOKEN = os.getenv("CHOICE_TOKEN")           # опционален (бронирования)

# Категории POS ID
HOT_CATEGORIES  = {4, 13, 15, 46, 33}                 # ЧЕБУРЕКИ, М'ЯСНІ, ЯНТИКИ, ГАРЯЧІ, ПІДЕ
COLD_CATEGORIES = {7, 8, 11, 16, 18, 19, 29, 32, 36, 44}

# Кэш
PRODUCT_CACHE = {}           # product_id -> menu_category_id
PRODUCT_CACHE_TS = 0
CACHE = {"hot": {}, "cold": {}, "hourly": {}, "bookings": []}
CACHE_TS = 0

# ===== Helpers =====
def _get(url, **kwargs):
    """GET с безопасным логом первых 1500 символов."""
    r = requests.get(url, timeout=kwargs.pop("timeout", 25))
    log_snippet = r.text[:1500].replace("\n", " ")
    print(f"DEBUG GET {url.split('?')[0]} -> {r.status_code} : {log_snippet}", file=sys.stderr, flush=True)
    r.raise_for_status()
    return r

# ===== Справочник товаров (пагинация) =====
def load_products():
    """Грузим ВСЕ товары обоих типов и строим product_id -> menu_category_id."""
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

# ===== Сводные продажи по категориям =====
def fetch_category_sales():
    today = date.today().strftime("%Y-%m-%d")
    url = (
        f"https://{ACCOUNT_NAME}.joinposter.com/api/dash.getCategoriesSales"
        f"?token={POSTER_TOKEN}&dateFrom={today}&dateTo={today}"
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

    # сортировка по убыванию
    hot = dict(sorted(hot.items(), key=lambda x: x[1], reverse=True))
    cold = dict(sorted(cold.items(), key=lambda x: x[1], reverse=True))
    return {"hot": hot, "cold": cold}

# ===== Почасовая диаграмма: чеки + справочник =====
def fetch_transactions_hourly():
    products = load_products()
    today = date.today().strftime("%Y-%m-%d")

    per_page = 500
    page = 1
    hours = list(range(8, 24))               # рабочие часы
    hot_by_hour = [0] * len(hours)
    cold_by_hour = [0] * len(hours)

    while True:
        url = (
            f"https://{ACCOUNT_NAME}.joinposter.com/api/transactions.getTransactions"
            f"?token={POSTER_TOKEN}&date_from={today}&date_to={today}"
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

        # пагинация
        if per_page_resp * page >= total:
            break
        page += 1

    # накопительно
    hot_cum, cold_cum = [], []
    th, tc = 0, 0
    for h, c in zip(hot_by_hour, cold_by_hour):
        th += h; tc += c
        hot_cum.append(th)
        cold_cum.append(tc)

    labels = [f"{h:02d}:00" for h in hours]
    return {"labels": labels, "hot": hot_cum, "cold": cold_cum}

# ===== Бронирования (мягкий режим) =====
def fetch_bookings():
    if not CHOICE_TOKEN:
        return []
    url = f"https://{ACCOUNT_NAME}.choiceqr.com/api/bookings/list"
    headers = {"Authorization": f"Bearer {CHOICE_TOKEN}"}
    try:
        resp = requests.get(url, headers=headers, timeout=20)
        data = resp.json()
    except Exception as e:
        print("ERROR Choice:", e, file=sys.stderr, flush=True)
        return []

    # разные инсталляции отдают по-разному — ищем массив
    items = None
    for key in ("items", "data", "list", "bookings", "response"):
        v = data.get(key)
        if isinstance(v, list):
            items = v; break
    if not items:
        return []

    out = []
    for b in items[:12]:  # компактно
        name = (b.get("customer") or {}).get("name") or b.get("name") or "—"
        guests = b.get("personCount") or b.get("persons") or b.get("guests") or "—"
        time_str = b.get("dateTime") or b.get("bookingDt") or b.get("startDateTime") or ""
        if isinstance(time_str, str) and len(time_str) >= 16:
            # оставим только HH:MM если ISO/SQL
            try:
                time_str = datetime.fromisoformat(time_str.replace("Z","+00:00")).strftime("%H:%M")
            except Exception:
                try:
                    time_str = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S").strftime("%H:%M")
                except Exception:
                    pass
        out.append({"name": name, "time": time_str or "—", "guests": guests})
    return out

# ===== API =====
@app.route("/api/sales")
def api_sales():
    global CACHE, CACHE_TS
    if time.time() - CACHE_TS > 60:
        sums = fetch_category_sales()
        hourly = fetch_transactions_hourly()
        bookings = fetch_bookings()
        CACHE.update({"hot": sums["hot"], "cold": sums["cold"], "hourly": hourly, "bookings": bookings})
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
                --hot:#ff8800; --cold:#33b5ff; --ok:#00d46a; --frame:#ffb000;
            }
            *{box-sizing:border-box}
            body{margin:0;background:var(--bg);color:var(--fg);font-family:Inter,Arial,sans-serif}
            .wrap{padding:18px;max-width:1600px;margin:0 auto}
            .row{display:grid;grid-template-columns:repeat(3,1fr);gap:18px}
            .card{
                background:var(--panel);
                border-radius:14px;
                padding:14px 16px;
                position:relative;
                outline:3px solid rgba(255,255,255,0.04); /* базовый контур */
                box-shadow:0 0 0 3px rgba(0,0,0,0) inset, 0 0 22px rgba(0,0,0,0.45);
            }
            .card.hot{ outline-color:rgba(255,136,0,0.45) }
            .card.cold{ outline-color:rgba(51,181,255,0.45) }
            .card.book{ outline-color:rgba(0,212,106,0.45) }
            .card.chart{
                grid-column:1/-1;
                outline-color:rgba(255,176,0,0.55);
            }
            h2{margin:4px 0 10px 0;font-size:26px;display:flex;align-items:center;gap:8px}
            table{width:100%;border-collapse:collapse;font-size:18px}
            td{padding:4px 2px}
            td:last-child{text-align:right}
            .logo{position:fixed;right:18px;bottom:12px;font-weight:800;letter-spacing:0.5px}
        </style>
    </head>
    <body>
        <div class="wrap">
            <div class="row">
                <div class="card hot">
                    <h2>🔥 Гарячий цех</h2>
                    <table id="hot_tbl"></table>
                </div>
                <div class="card cold">
                    <h2>❄️ Холодний цех</h2>
                    <table id="cold_tbl"></table>
                </div>
                <div class="card book">
                    <h2>📅 Бронювання</h2>
                    <table id="book_tbl"></table>
                </div>
                <div class="card chart">
                    <h2>📊 Замовлення по годинах (накопич.)</h2>
                    <canvas id="chart" height="160"></canvas>
                </div>
            </div>
        </div>
        <div class="logo">GRECO</div>

        <script>
        let chart;
        async function refresh(){
            const r = await fetch('/api/sales'); const data = await r.json();

            function fill(id, obj){
                const el = document.getElementById(id);
                let html = "";
                Object.entries(obj).forEach(([k,v]) => html += `<tr><td>${k}</td><td>${v}</td></tr>`);
                if(!html) html = "<tr><td>—</td><td>0</td></tr>";
                el.innerHTML = html;
            }
            fill('hot_tbl', data.hot || {});
            fill('cold_tbl', data.cold || {});

            const b = document.getElementById('book_tbl');
            b.innerHTML = (data.bookings||[]).map(x => `<tr><td>${x.name}</td><td>${x.time}</td><td>${x.guests}</td></tr>`).join('') || "<tr><td>—</td><td></td><td></td></tr>";

            const labels = (data.hourly&&data.hourly.labels)||[];
            const hot = (data.hourly&&data.hourly.hot)||[];
            const cold = (data.hourly&&data.hourly.cold)||[];

            const ctx = document.getElementById('chart').getContext('2d');
            if(chart) chart.destroy();
            chart = new Chart(ctx,{
                type:'line',
                data:{
                    labels:labels,
                    datasets:[
                        {label:'Гарячий', data:hot, borderColor:'#ff8800', backgroundColor:'#ff8800', tension:0.25, fill:false},
                        {label:'Холодний', data:cold, borderColor:'#33b5ff', backgroundColor:'#33b5ff', tension:0.25, fill:false}
                    ]
                },
                options:{
                    responsive:true,
                    plugins:{legend:{labels:{color:'#ddd'}}},
                    scales:{x:{ticks:{color:'#bbb'}}, y:{ticks:{color:'#bbb'}, beginAtZero:true}}
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
