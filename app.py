import os
import time
import requests
import sys
from datetime import datetime, timedelta
from flask import Flask, render_template_string, jsonify

app = Flask(__name__)

# ==== Конфиг ====
ACCOUNT_NAME = "poka-net3"
POSTER_TOKEN = os.getenv("POSTER_TOKEN")           # обязателен
CHOICE_TOKEN = os.getenv("CHOICE_TOKEN")           # опционален (бронирования)

# Категории POS ID
HOT_CATEGORIES  = {4, 13, 15, 46, 33}
COLD_CATEGORIES = {7, 8, 11, 16, 18, 19, 29, 32, 36, 44}

# Кэш
CACHE = {"hot": {}, "cold": {}, "hourly": {}, "bookings": []}
CACHE_TS = 0


# ===== Helpers =====
def _get(url, **kwargs):
    r = requests.get(url, timeout=kwargs.pop("timeout", 25))
    log_snippet = r.text[:300].replace("\n", " ")
    print(f"DEBUG GET {url.split('?')[0]} -> {r.status_code} : {log_snippet}", file=sys.stderr, flush=True)
    r.raise_for_status()
    return r


# ===== Продажи по категориям =====
def fetch_category_sales():
    today = datetime.now().strftime("%Y-%m-%d")
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
    hot = dict(sorted(hot.items(), key=lambda x: x[1], reverse=True))
    cold = dict(sorted(cold.items(), key=lambda x: x[1], reverse=True))
    return {"hot": hot, "cold": cold}


# ===== Почасовая диаграмма через dash.getAnalytics =====
def fetch_transactions_hourly():
    today = datetime.now().date()
    last_week = today - timedelta(days=7)

    def get_day(day):
        url = (
            f"https://{ACCOUNT_NAME}.joinposter.com/api/dash.getAnalytics"
            f"?token={POSTER_TOKEN}&dateFrom={day.strftime('%Y%m%d')}&dateTo={day.strftime('%Y%m%d')}"
            f"&interpolate=hour&type=categories"
        )
        try:
            resp = _get(url)
            categories = resp.json().get("response", [])
        except Exception as e:
            print("ERROR analytics:", e, file=sys.stderr, flush=True)
            return [0]*24, [0]*24

        hot_hours = [0]*24
        cold_hours = [0]*24
        for cat in categories:
            try:
                cid = int(cat.get("category_id", 0))
                hourly = cat.get("data_hourly", [])
                hourly = [int(float(x)) if x else 0 for x in hourly]
            except Exception:
                continue
            if cid in HOT_CATEGORIES:
                hot_hours = [h+c for h,c in zip(hot_hours, hourly)]
            elif cid in COLD_CATEGORIES:
                cold_hours = [h+c for h,c in zip(cold_hours, hourly)]

        # накопительно
        hot_cum, cold_cum = [], []
        th, tc = 0, 0
        for h, c in zip(hot_hours, cold_hours):
            th += h; tc += c
            hot_cum.append(th)
            cold_cum.append(tc)

        return hot_cum, cold_cum

    hot_today, cold_today = get_day(today)
    hot_prev, cold_prev = get_day(last_week)

    # обрезаем по текущему часу
    now_hour = datetime.now().hour
    for i in range(24):
        if i > now_hour:
            hot_today[i] = None
            cold_today[i] = None

    labels = [f"{h:02d}:00" for h in range(10, 23)]
    return {
        "labels": labels,
        "hot": hot_today[10:23],
        "cold": cold_today[10:23],
        "hot_prev": hot_prev[10:23],
        "cold_prev": cold_prev[10:23]
    }


# ===== Бронирования =====
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
    items = None
    for key in ("items", "data", "list", "bookings", "response"):
        v = data.get(key)
        if isinstance(v, list):
            items = v; break
    if not items:
        return []
    out = []
    for b in items[:12]:
        name = (b.get("customer") or {}).get("name") or b.get("name") or "—"
        guests = b.get("personCount") or b.get("persons") or b.get("guests") or "—"
        time_str = b.get("dateTime") or b.get("bookingDt") or b.get("startDateTime") or ""
        if isinstance(time_str, str) and len(time_str) >= 16:
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
        CACHE.update({
            "hot": sums["hot"],
            "cold": sums["cold"],
            "hourly": hourly,
            "bookings": bookings
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
            body{margin:0;background:#0f0f0f;color:#eee;font-family:Inter,Arial,sans-serif}
            .wrap{padding:18px;max-width:1600px;margin:0 auto}
            .row{display:grid;grid-template-columns:repeat(3,1fr);gap:18px}
            .card{background:#151515;border-radius:14px;padding:14px 16px}
            .card.chart{grid-column:1/-1}
            h2{margin:4px 0 10px 0;font-size:26px}
            table{width:100%;border-collapse:collapse;font-size:18px}
            td{padding:4px 2px} td:last-child{text-align:right}
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
            b.innerHTML = (data.bookings||[]).map(x => `<tr><td>${x.name}</td><td>${x.time}</td><td>${x.guests}</td></tr>`).join('') || "<tr><td>—</td></tr>";

            const labels = (data.hourly&&data.hourly.labels)||[];
            const hot = (data.hourly&&data.hourly.hot)||[];
            const cold = (data.hourly&&data.hourly.cold)||[];
            const hot_prev = (data.hourly&&data.hourly.hot_prev)||[];
            const cold_prev = (data.hourly&&data.hourly.cold_prev)||[];

            const ctx = document.getElementById('chart').getContext('2d');
            if(chart) chart.destroy();
            chart = new Chart(ctx,{
                type:'line',
                data:{
                    labels:labels,
                    datasets:[
                        {label:'Гарячий (сегодня)', data:hot, borderColor:'#ff8800', borderWidth:3, tension:0.25, fill:false, spanGaps:false},
                        {label:'Холодний (сегодня)', data:cold, borderColor:'#33b5ff', borderWidth:3, tension:0.25, fill:false, spanGaps:false},
                        {label:'Гарячий (прошлая неделя)', data:hot_prev, borderColor:'#ffbb66', borderWidth:2, borderDash:[6,4], tension:0.25, fill:false, spanGaps:false},
                        {label:'Холодний (прошлая неделя)', data:cold_prev, borderColor:'#66cfff', borderWidth:2, borderDash:[6,4], tension:0.25, fill:false, spanGaps:false}
                    ]
                },
                options:{
                    responsive:true,
                    plugins:{legend:{labels:{color:'#ddd'}}},
                    scales:{
                        x:{ticks:{color:'#bbb'}, min:"10:00", max:"22:00"},
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
