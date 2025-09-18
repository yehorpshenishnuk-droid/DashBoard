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
    log_snippet = r.text[:800].replace("\n", " ")
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

def fetch_category_names_for_today():
    """
    Берём имена категорий (id -> name) с dash.getCategoriesSales за сегодня.
    Имя нужно для красивой таблицы; суммы тут не используем.
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
        print("ERROR fetch_category_names_for_today:", e, file=sys.stderr, flush=True)
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
    """
    Кумулятив по часам для графика (горячий/холодный целиком по дню).
    """
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
    """
    - Таблицы: для «Сьогодні» и «Мин. тиждень» считаем до текущего часа по транзакциям.
    - График: сегодня — обрезка по текущему часу (в браузере), прошл. неделя — полный день.
    """
    global CACHE, CACHE_TS
    if time.time() - CACHE_TS > 60:
        now_hour = datetime.now().hour

        # Имена категорий по сегодняшнему дню
        cat_names = fetch_category_names_for_today()

        # Таблицы — до текущего часа
        hot_today, cold_today = aggregate_categories_until(day_offset=0, until_hour=now_hour)
        hot_prev,  cold_prev  = aggregate_categories_until(day_offset=7, until_hour=now_hour)

        # Преобразуем в {name: qty}, используя имена; если имени нет — "Категорія <id>"
        def by_name(dct):
            out = {}
            for cid, qty in dct.items():
                name = cat_names.get(cid, f"Категорія {cid}")
                out[name] = qty
            return out

        hourly_today = fetch_transactions_hourly(0)
        hourly_prev  = fetch_transactions_hourly(7)  # ПОЛНЫЙ день для графика прошлой недели

        CACHE.update({
            "hot": by_name(hot_today),
            "cold": by_name(cold_today),
            "hot_prev": by_name(hot_prev),
            "cold_prev": by_name(cold_prev),
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
            :root {
                --bg:#0f0f0f; --panel:#151515; --fg:#eee;
                --hot:#ff8800; --cold:#33b5ff;
            }
            *{box-sizing:border-box}
            html,body{height:100%;margin:0}
            body{background:var(--bg);color:var(--fg);font-family:Inter,Arial,sans-serif}
            .wrap{height:100vh;max-width:1920px;margin:0 auto;padding:10px;display:grid;grid-template-rows:auto 1fr;gap:10px}
            .top{display:grid;grid-template-columns:1fr 1fr;gap:10px;min-height:0}
            .card{background:var(--panel);border-radius:10px;padding:10px;min-height:0}
            h2{font-size:18px;margin:0 0 8px 0}
            table{width:100%;border-collapse:collapse;font-size:16px;line-height:1.2}
            th,td{padding:4px 6px;text-align:right;white-space:nowrap}
            th:first-child, td:first-child{text-align:left}
            td.today{font-weight:800;color:#fff}
            td.prev{color:#8a8f98;font-weight:600}
            .chart-card{min-height:0;display:flex;flex-direction:column}
            .chart-wrap{flex:1;min-height:0}
            canvas{max-height:100%;width:100%}
            .logo{position:fixed;right:12px;bottom:8px;font-weight:800;font-size:14px;opacity:.9}
            /* Смартфоны: складываем график под таблицы */
            @media (max-width: 900px){
                .wrap{grid-template-rows:auto auto auto;gap:8px}
                .top{grid-template-columns:1fr;gap:8px}
                h2{font-size:16px}
                table{font-size:14px}
            }
        </style>
    </head>
    <body>
        <div class="wrap">
            <div class="top">
                <div class="card">
                    <h2>🔥 Гарячий цех</h2>
                    <table id="hot_tbl">
                        <thead><tr><th>Категорія</th><th>Сьогодні</th><th>Мин. тиждень</th></tr></thead>
                        <tbody></tbody>
                    </table>
                </div>
                <div class="card">
                    <h2>❄️ Холодний цех</h2>
                    <table id="cold_tbl">
                        <thead><tr><th>Категорія</th><th>Сьогодні</th><th>Мин. тиждень</th></tr></thead>
                        <tbody></tbody>
                    </table>
                </div>
            </div>

            <div class="card chart-card">
                <h2>📊 Замовлення по годинах (накопич.)</h2>
                <div class="chart-wrap">
                    <!-- занимаем ~45% высоты экрана на ТВ, но адаптивно тянется -->
                    <canvas id="chart" style="height:45vh;"></canvas>
                </div>
            </div>
        </div>
        <div class="logo">GRECO Tech ™</div>

        <script>
        let chart;

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

            function fill(tableId, todayObj, prevObj){
                const tbody = document.querySelector("#" + tableId + " tbody");
                const cats = Array.from(new Set([...Object.keys(todayObj||{}), ...Object.keys(prevObj||{})]));
                cats.sort((a,b)=>a.localeCompare(b,'uk')); // сортировка по имени
                let html = "";
                cats.forEach(cat => {
                    const t = todayObj[cat] || 0;
                    const p = prevObj[cat] || 0;
                    html += `<tr><td>${cat}</td><td class="today">${t}</td><td class="prev">${p}</td></tr>`;
                });
                tbody.innerHTML = html || "<tr><td>—</td><td class='today'>0</td><td class='prev'>0</td></tr>";
            }

            fill('hot_tbl',  data.hot  || {}, data.hot_prev  || {});
            fill('cold_tbl', data.cold || {}, data.cold_prev || {});

            // График: сегодня до текущего часа, прошлый — полный день
            const todayCut = cutToNow(data.hourly.labels, data.hourly.hot, data.hourly.cold);
            const prevFull = { labels: data.hourly_prev.labels, hot: data.hourly_prev.hot, cold: data.hourly_prev.cold };

            const ctx = document.getElementById('chart').getContext('2d');
            if(chart) chart.destroy();
            chart = new Chart(ctx,{
                type:'line',
                data:{
                    labels: data.hourly.labels,
                    datasets:[
                        {label:'Гарячий', data:todayCut.hot, borderColor:'#ff8800', tension:0.25, fill:false},
                        {label:'Холодний', data:todayCut.cold, borderColor:'#33b5ff', tension:0.25, fill:false},
                        {label:'Гарячий (мин. тижд.)', data:prevFull.hot, borderColor:'#ff8800', borderDash:[6,4], tension:0.25, fill:false},
                        {label:'Холодний (мин. тижд.)', data:prevFull.cold, borderColor:'#33b5ff', borderDash:[6,4], tension:0.25, fill:false}
                    ]
                },
                options:{
                    responsive:true,
                    maintainAspectRatio:false,
                    plugins:{legend:{labels:{color:'#ddd', font:{size:14}}}},
                    scales:{
                        x:{ticks:{color:'#bbb', font:{size:12}}},
                        y:{ticks:{color:'#bbb', font:{size:12}}, beginAtZero:true}
                    }
                }
            });
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
