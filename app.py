import os
import time
import requests
import sys
from datetime import date, datetime, timedelta
from flask import Flask, render_template_string, jsonify

app = Flask(__name__)

# ==== Конфиг ====
ACCOUNT_NAME = "poka-net3"
POSTER_TOKEN = os.getenv("POSTER_TOKEN")  # обязательный

# Категории POS ID
HOT_CATEGORIES = {4, 13, 15, 46, 33}  # Гарячий цех
COLD_CATEGORIES = {7, 8, 11, 16, 18, 19, 29, 32, 36, 44}  # Холодний цех
BAR_CATEGORIES = {9, 14, 27, 28, 34, 41, 42, 47, 22, 24, 25, 26, 39, 30}  # Бар

# Кэш
PRODUCT_CACHE = {}
PRODUCT_CACHE_TS = 0
CACHE = {
    "hot": {},
    "cold": {},
    "bar": {},
    "shares": {},
    "hourly": {},
    "hourly_prev": {},
}
CACHE_TS = 0


# ===== Вспомогательная функция для запросов =====
def _get(url, **kwargs):
    r = requests.get(url, timeout=kwargs.pop("timeout", 25))
    log_snippet = r.text[:1500].replace("\n", " ")
    print(
        f"DEBUG GET {url.split('?')[0]} -> {r.status_code} : {log_snippet}",
        file=sys.stderr,
        flush=True,
    )
    r.raise_for_status()
    return r


# ===== Сводные продажи =====
def fetch_category_sales(target_date):
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

    return {"hot": hot, "cold": cold, "bar": bar}


# ===== Почасовые данные для графика =====
def fetch_transactions_hourly(day_offset=0):
    target_date = (date.today() - timedelta(days=day_offset)).strftime("%Y-%m-%d")
    url = (
        f"https://{ACCOUNT_NAME}.joinposter.com/api/transactions.getTransactions"
        f"?token={POSTER_TOKEN}&date_from={target_date}&date_to={target_date}"
        f"&per_page=500&page=1"
    )
    try:
        resp = _get(url)
        body = resp.json().get("response", {})
        items = body.get("data", []) or []
    except Exception as e:
        print("ERROR transactions:", e, file=sys.stderr, flush=True)
        return {"labels": [], "hot": [], "cold": []}

    hours = list(range(10, 23))
    hot_by_hour = [0] * len(hours)
    cold_by_hour = [0] * len(hours)

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
            # здесь можно доработать, если нужно учитывать bar
            # пока считаем только hot/cold
            pass

    labels = [f"{h:02d}:00" for h in hours]
    return {"labels": labels, "hot": hot_by_hour, "cold": cold_by_hour}


# ===== API =====
@app.route("/api/sales")
def api_sales():
    global CACHE, CACHE_TS
    if time.time() - CACHE_TS > 60:
        today = date.today().strftime("%Y-%m-%d")
        sums_today = fetch_category_sales(today)

        total_hot = sum(sums_today["hot"].values())
        total_cold = sum(sums_today["cold"].values())
        total_bar = sum(sums_today["bar"].values())
        total = total_hot + total_cold + total_bar

        shares = {}
        if total > 0:
            shares = {
                "hot": round(total_hot / total * 100, 1),
                "cold": round(total_cold / total * 100, 1),
                "bar": round(total_bar / total * 100, 1),
            }

        hourly = fetch_transactions_hourly(0)
        prev = fetch_transactions_hourly(7)

        CACHE.update(
            {
                "hot": sums_today["hot"],
                "cold": sums_today["cold"],
                "bar": sums_today["bar"],
                "shares": shares,
                "hourly": hourly,
                "hourly_prev": prev,
            }
        )
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
            body{margin:0;background:var(--bg);color:var(--fg);font-family:Inter,Arial,sans-serif}
            .wrap{padding:18px;max-width:1600px;margin:0 auto}
            .row{display:grid;grid-template-columns:repeat(2,1fr);gap:18px}
            .card{background:var(--panel);border-radius:14px;padding:14px 16px;}
            .card.chart{grid-column:1/-1;}
            .card.pie{grid-column:1/-1;}
            table{width:100%;border-collapse:collapse;font-size:18px}
            th, td{padding:4px 2px} td:last-child{text-align:right}
            th{text-align:left;color:#aaa;font-weight:600}
            .logo{position:fixed;right:18px;bottom:12px;font-weight:800}
        </style>
    </head>
    <body>
        <div class="wrap">
            <div class="row">
                <div class="card hot">
                    <h2>🔥 Гарячий цех</h2>
                    <table id="hot_tbl">
                        <tr><th>Категорія</th><th>Сьогодні</th></tr>
                    </table>
                </div>
                <div class="card cold">
                    <h2>❄️ Холодний цех</h2>
                    <table id="cold_tbl">
                        <tr><th>Категорія</th><th>Сьогодні</th></tr>
                    </table>
                </div>
                <div class="card pie"><h2>📊 Розподіл замовлень</h2><canvas id="pie" height="200"></canvas></div>
                <div class="card chart"><h2>📊 Замовлення по годинах (накопич.)</h2><canvas id="chart" height="160"></canvas></div>
            </div>
        </div>
        <div class="logo">GRECO</div>

        <script>
        let chart, pie;

        async function refresh(){
            const r = await fetch('/api/sales');
            const data = await r.json();

            function fill(id, obj){
                const el = document.getElementById(id);
                let html = "<tr><th>Категорія</th><th>Сьогодні</th></tr>";
                Object.entries(obj).forEach(([k,v]) => html += `<tr><td>${k}</td><td>${v}</td></tr>`);
                if(Object.keys(obj).length===0) html += "<tr><td>—</td><td>0</td></tr>";
                el.innerHTML = html;
            }
            fill('hot_tbl', data.hot || {});
            fill('cold_tbl', data.cold || {});

            // круговая диаграмма
            const ctxPie = document.getElementById('pie').getContext('2d');
            if(pie) pie.destroy();
            pie = new Chart(ctxPie, {
                type:'doughnut',
                data:{
                    labels:['Бар','Гарячий цех','Холодний цех'],
                    datasets:[{
                        data:[data.shares.bar||0, data.shares.hot||0, data.shares.cold||0],
                        backgroundColor:['#9b59b6','#ff8800','#33b5ff']
                    }]
                },
                options:{
                    responsive:true,
                    plugins:{
                        legend:{labels:{color:'#ddd'}},
                        datalabels:{
                            color:'#fff',
                            formatter:(value, ctx)=>{
                                let label = ctx.chart.data.labels[ctx.dataIndex];
                                return label + ' ' + value + '%';
                            }
                        }
                    }
                },
                plugins:[ChartDataLabels]
            });

            // график по часам
            const ctx = document.getElementById('chart').getContext('2d');
            if(chart) chart.destroy();
            chart = new Chart(ctx,{
                type:'line',
                data:{
                    labels: data.hourly.labels,
                    datasets:[
                        {label:'Гарячий', data:data.hourly.hot, borderColor:'#ff8800', tension:0.25, fill:false},
                        {label:'Холодний', data:data.hourly.cold, borderColor:'#33b5ff', tension:0.25, fill:false},
                        {label:'Гарячий (мин. тижд.)', data:data.hourly_prev.hot, borderColor:'#ff8800', borderDash:[6,4], tension:0.25, fill:false},
                        {label:'Холодний (мин. тижд.)', data:data.hourly_prev.cold, borderColor:'#33b5ff', borderDash:[6,4], tension:0.25, fill:false}
                    ]
                },
                options:{
                    responsive:true,
                    plugins:{legend:{labels:{color:'#ddd'}}},
                    scales:{
                        x:{ticks:{color:'#bbb'}},
                        y:{ticks:{color:'#bbb'},beginAtZero:true}
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
