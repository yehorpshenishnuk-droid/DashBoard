import os
import time
import requests
import sys
from datetime import date, datetime, timedelta
from flask import Flask, render_template_string, jsonify, make_response

app = Flask(__name__)

# ==== Конфиг ====
ACCOUNT_NAME = "poka-net3"
POSTER_TOKEN = os.getenv("POSTER_TOKEN")           # обязателен
CHOICE_TOKEN = os.getenv("CHOICE_TOKEN")           # опционален
WEATHER_KEY = os.getenv("WEATHER_KEY", "")         # API ключ OpenWeather

# Категории POS ID
HOT_CATEGORIES  = {4, 13, 15, 46, 33}
COLD_CATEGORIES = {7, 8, 11, 16, 18, 19, 29, 32, 36, 44}
BAR_CATEGORIES  = {9,14,27,28,34,41,42,47,22,24,25,26,39,30}

# Кэш
PRODUCT_CACHE = {}
PRODUCT_CACHE_TS = 0
CACHE = {"hot": {}, "cold": {}, "hot_prev": {}, "cold_prev": {},
         "hourly": {}, "hourly_prev": {}, "share": {}, "weather": {}}
CACHE_TS = 0

# ===== Helpers =====
def _get(url, **kwargs):
    r = requests.get(url, timeout=kwargs.pop("timeout", 25))
    log_snippet = r.text[:500].replace("\n", " ")
    print(f"DEBUG GET {url.split('?')[0]} -> {r.status_code} : {log_snippet}", file=sys.stderr, flush=True)
    r.raise_for_status()
    return r

# ===== API DATA FUNCTIONS =====
def fetch_category_sales(day_offset=0):
    target_date = (date.today() - timedelta(days=day_offset)).strftime("%Y-%m-%d")
    url = f"https://{ACCOUNT_NAME}.joinposter.com/api/dash.getCategoriesSales?token={POSTER_TOKEN}&dateFrom={target_date}&dateTo={target_date}"
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

    return {"hot": dict(sorted(hot.items())), "cold": dict(sorted(cold.items())), "bar": dict(sorted(bar.items()))}

def fetch_weather():
    if not WEATHER_KEY:
        return {"temp": "Н/Д", "desc": "Н/Д", "icon": ""}
    try:
        url = f"https://api.openweathermap.org/data/2.5/weather?lat=50.395&lon=30.355&appid={WEATHER_KEY}&units=metric&lang=uk"
        resp = requests.get(url, timeout=10)
        data = resp.json()
        return {"temp": f"{round(data['main']['temp'])}°C",
                "desc": data["weather"][0]["description"].capitalize(),
                "icon": data["weather"][0]["icon"]}
    except Exception as e:
        print("ERROR weather:", e, file=sys.stderr, flush=True)
        return {"temp": "Н/Д", "desc": "Н/Д", "icon": ""}

HALL_TABLES = [1,2,3,4,5,6,8]
TERRACE_TABLES = [7,10,11,12,13]

def fetch_tables_with_waiters():
    target_date = date.today().strftime("%Y%m%d")
    url = f"https://{ACCOUNT_NAME}.joinposter.com/api/dash.getTransactions?token={POSTER_TOKEN}&dateFrom={target_date}&dateTo={target_date}"
    try:
        resp = _get(url)
        rows = resp.json().get("response", [])
    except Exception as e:
        print("ERROR tables:", e, file=sys.stderr, flush=True)
        rows = []

    active = {}
    for trx in rows:
        try:
            if int(trx.get("status", 0)) == 2:
                continue
            tname = int(trx.get("table_name", 0))
            waiter = trx.get("name", "—")
            active[tname] = waiter
        except Exception:
            continue

    def build(nums):
        return [{"id": t, "name": f"Стол {t}", "waiter": active.get(t, "—"), "occupied": t in active} for t in nums]

    return {"hall": build(HALL_TABLES), "terrace": build(TERRACE_TABLES)}

# ===== API =====
@app.route("/api/sales")
def api_sales():
    global CACHE, CACHE_TS
    if time.time() - CACHE_TS > 60:
        sums_today = fetch_category_sales(0)
        sums_prev = fetch_category_sales(7)
        total_hot = sum(sums_today["hot"].values())
        total_cold = sum(sums_today["cold"].values())
        total_bar = sum(sums_today["bar"].values())
        total = total_hot + total_cold + total_bar
        share = {"hot": round(total_hot/total*100) if total else 0,
                 "cold": round(total_cold/total*100) if total else 0,
                 "bar": round(total_bar/total*100) if total else 0}
        CACHE.update({"hot": sums_today["hot"], "cold": sums_today["cold"],
                      "hot_prev": sums_prev["hot"], "cold_prev": sums_prev["cold"],
                      "share": share, "weather": fetch_weather()})
        CACHE_TS = time.time()
    return jsonify(CACHE)

@app.route("/api/tables")
def api_tables():
    resp = make_response(jsonify(fetch_tables_with_waiters()))
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return resp

# ===== UI =====
@app.route("/")
def index():
    template = """
    <html>
    <head>
    <meta charset="utf-8"/>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-datalabels@2"></script>
    <style>
      :root {--bg:#0f0f0f;--panel:#151515;--fg:#eee;
             --hot:#ff8800;--cold:#33b5ff;--bar:#9b59b6;}
      body{margin:0;background:var(--bg);color:var(--fg);font-family:Inter,Arial,sans-serif;overflow:hidden}
      .wrap{padding:8px;max-width:100%;margin:0 auto}
      .row{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:8px}
      .card{background:var(--panel);border-radius:10px;padding:8px}
      .card.small{height:160px;overflow:auto}
      .card.chart{grid-column:span 2;height:300px}
      .card.tables{grid-column:span 2;height:300px;overflow:auto}
      table{width:100%;font-size:14px}
      th,td{padding:2px 4px;text-align:right}
      th:first-child,td:first-child{text-align:left}
      canvas{max-width:100%}
      .tables-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:6px}
      .table-tile{border-radius:6px;padding:10px;font-weight:bold;text-align:center;font-size:14px}
      .occupied{background:#33b5ff;color:#000;}
      .free{background:#555;color:#fff;}
    </style>
    </head>
    <body>
    <div class="wrap">
      <div class="row">
        <div class="card small"><h3>🔥 Гарячий цех</h3><table id="hot_tbl"></table></div>
        <div class="card small"><h3>❄️ Холодний цех</h3><table id="cold_tbl"></table></div>
        <div class="card small"><h3>📊 Розподіл</h3><canvas id="pie"></canvas></div>
        <div class="card small"><h3>🕒 Час і погода</h3>
          <div id="clock" style="font-size:20px;margin-top:4px"></div>
          <div id="weather" style="margin-top:6px;font-size:14px"></div>
        </div>
      </div>
      <div class="row">
        <div class="card chart"><h3>📈 Замовлення по годинах</h3><canvas id="chart"></canvas></div>
        <div class="card tables"><h3>🍴 Зал / 🌿 Тераса</h3>
          <div id="hall" class="tables-grid"></div>
          <div id="terrace" class="tables-grid" style="margin-top:6px"></div>
        </div>
      </div>
    </div>

    <script>
    let chart, pie;

    function renderTables(zoneId, data){
      const el = document.getElementById(zoneId);
      el.innerHTML="";
      data.forEach(t=>{
        const div=document.createElement("div");
        div.className="table-tile "+(t.occupied?"occupied":"free");
        div.innerHTML=`<div>${t.name}</div><div>${t.waiter}</div>`;
        el.appendChild(div);
      });
    }

    async function refresh(){
      const r=await fetch('/api/sales'); const data=await r.json();
      function fill(id,today,prev){
        let html="<tr><th>Категорія</th><th>Сьогодні</th><th>Мин. тиждень</th></tr>";
        const keys=new Set([...Object.keys(today),...Object.keys(prev)]);
        keys.forEach(k=>{html+=`<tr><td>${k}</td><td>${today[k]||0}</td><td>${prev[k]||0}</td></tr>`});
        document.getElementById(id).innerHTML=html;
      }
      fill('hot_tbl',data.hot||{},data.hot_prev||{});
      fill('cold_tbl',data.cold||{},data.cold_prev||{});
      Chart.register(ChartDataLabels);
      const ctx2=document.getElementById('pie').getContext('2d');
      if(pie) pie.destroy();
      pie=new Chart(ctx2,{type:'pie',
        data:{labels:['Гарячий','Холодний','Бар'],
              datasets:[{data:[data.share.hot,data.share.cold,data.share.bar],
                         backgroundColor:['#ff8800','#33b5ff','#9b59b6']}]},
        options:{plugins:{legend:{display:false},tooltip:{enabled:false},
                datalabels:{color:'#fff',font:{weight:'bold',size:12},
                formatter:(v,c)=>c.chart.data.labels[c.dataIndex]+"\\n"+v+"%"}}}});
      const ctx=document.getElementById('chart').getContext('2d');
      if(chart) chart.destroy();
      chart=new Chart(ctx,{type:'line',
        data:{labels:["10","11","12","13","14","15","16","17","18","19","20","21","22"],
              datasets:[{label:'Гарячий',data:[1,2,3],borderColor:'#ff8800'},
                        {label:'Холодний',data:[2,3,4],borderColor:'#33b5ff'}]},
        options:{responsive:true,plugins:{legend:{labels:{color:'#ddd'}},datalabels:{display:false}},
                 scales:{x:{ticks:{color:'#bbb'}},y:{ticks:{color:'#bbb'},beginAtZero:true}}}});
      document.getElementById('clock').innerText=new Date().toLocaleTimeString('uk-UA',{hour:'2-digit',minute:'2-digit'});
      const w=data.weather||{}; document.getElementById('weather').innerHTML=`${w.temp||'—'}<br>${w.desc||'—'}`;
    }

    async function refreshTables(){
      const r=await fetch('/api/tables'); const data=await r.json();
      renderTables('hall',data.hall||[]); renderTables('terrace',data.terrace||[]);
    }

    refresh(); refreshTables();
    setInterval(refresh,60000);
    setInterval(refreshTables,30000);
    </script>
    </body></html>
    """
    return render_template_string(template)

if __name__=="__main__":
    port=int(os.getenv("PORT",5000))
    app.run(host="0.0.0.0",port=port)
