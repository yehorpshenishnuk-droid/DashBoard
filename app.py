import os
import time
import requests
import sys
from datetime import date, datetime, timedelta
from flask import Flask, render_template_string, jsonify

app = Flask(__name__)

# ==== Конфиг ====
ACCOUNT_NAME = "poka-net3"
POSTER_TOKEN = os.getenv("POSTER_TOKEN")
CHOICE_TOKEN = os.getenv("CHOICE_TOKEN")
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")

# Категории POS ID
HOT_CATEGORIES  = {4, 13, 15, 46, 33}
COLD_CATEGORIES = {7, 8, 11, 16, 18, 19, 29, 32, 36, 44}
BAR_CATEGORIES  = {9, 14, 27, 28, 34, 41, 42, 47, 22, 24, 25, 26, 39, 30}

# Кэш
PRODUCT_CACHE, PRODUCT_CACHE_TS = {}, 0
CACHE, CACHE_TS = {}, 0

# ===== Helpers =====
def _get(url, **kwargs):
    r = requests.get(url, timeout=kwargs.pop("timeout", 25))
    r.raise_for_status()
    return r

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
            resp = _get(url).json().get("response", [])
            if not isinstance(resp, list) or not resp:
                break
            for item in resp:
                pid, cid = int(item.get("product_id", 0)), int(item.get("menu_category_id", 0))
                if pid and cid:
                    mapping[pid] = cid
            if len(resp) < per_page:
                break
            page += 1
    PRODUCT_CACHE, PRODUCT_CACHE_TS = mapping, time.time()
    return PRODUCT_CACHE

def fetch_category_sales(day_offset=0, cut_to_now=False):
    products = load_products()
    target_date = (date.today() - timedelta(days=day_offset)).strftime("%Y-%m-%d")
    per_page, page = 500, 1
    hot, cold, bar = {}, {}, {}
    now_hour = datetime.now().hour if cut_to_now else 23
    while True:
        url = (
            f"https://{ACCOUNT_NAME}.joinposter.com/api/transactions.getTransactions"
            f"?token={POSTER_TOKEN}&date_from={target_date}&date_to={target_date}"
            f"&per_page={per_page}&page={page}"
        )
        resp = _get(url).json().get("response", {})
        items = resp.get("data", []) or []
        total, page_info = int(resp.get("count", 0)), resp.get("page", {}) or {}
        if not items:
            break
        for trx in items:
            dt_str = trx.get("date_close")
            try:
                dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
                if cut_to_now and dt.hour > now_hour:
                    continue
            except Exception:
                continue
            for p in trx.get("products", []) or []:
                pid, qty = int(p.get("product_id", 0)), int(float(p.get("num", 0)))
                cid = products.get(pid, 0)
                if cid in HOT_CATEGORIES:
                    hot[trx.get("category_name","Гарячий")] = hot.get(trx.get("category_name","Гарячий"),0)+qty
                elif cid in COLD_CATEGORIES:
                    cold[trx.get("category_name","Холодний")] = cold.get(trx.get("category_name","Холодний"),0)+qty
                elif cid in BAR_CATEGORIES:
                    bar[trx.get("category_name","Бар")] = bar.get(trx.get("category_name","Бар"),0)+qty
        if int(page_info.get("per_page", per_page)) * page >= total:
            break
        page += 1
    return {"hot": hot, "cold": cold, "bar": bar}

def fetch_transactions_hourly(day_offset=0):
    products = load_products()
    target_date = (date.today() - timedelta(days=day_offset)).strftime("%Y-%m-%d")
    per_page, page = 500, 1
    hours = list(range(10, 23))
    hot_by_hour, cold_by_hour = [0]*len(hours), [0]*len(hours)
    while True:
        url = (
            f"https://{ACCOUNT_NAME}.joinposter.com/api/transactions.getTransactions"
            f"?token={POSTER_TOKEN}&date_from={target_date}&date_to={target_date}"
            f"&per_page={per_page}&page={page}"
        )
        resp = _get(url).json().get("response", {})
        items = resp.get("data", []) or []
        total, page_info = int(resp.get("count", 0)), resp.get("page", {}) or {}
        if not items: break
        for trx in items:
            dt_str = trx.get("date_close")
            try:
                dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
                if dt.hour not in hours: continue
                idx = hours.index(dt.hour)
            except Exception:
                continue
            for p in trx.get("products", []) or []:
                pid, qty = int(p.get("product_id", 0)), int(float(p.get("num", 0)))
                cid = products.get(pid, 0)
                if cid in HOT_CATEGORIES: hot_by_hour[idx]+=qty
                elif cid in COLD_CATEGORIES: cold_by_hour[idx]+=qty
        if int(page_info.get("per_page", per_page)) * page >= total: break
        page+=1
    hot_cum,cold_cum=[],[]
    th,tc=0,0
    for h,c in zip(hot_by_hour,cold_by_hour):
        th+=h;tc+=c
        hot_cum.append(th);cold_cum.append(tc)
    return {"labels":[f"{h:02d}:00" for h in hours],"hot":hot_cum,"cold":cold_cum}

def fetch_weather():
    if not WEATHER_API_KEY: return {}
    url=f"http://api.openweathermap.org/data/2.5/weather?q=Софіївська Борщагівка,UA&appid={WEATHER_API_KEY}&units=metric&lang=ua"
    try:
        data=requests.get(url,timeout=10).json()
        return {
            "temp": round(data["main"]["temp"]),
            "desc": data["weather"][0]["description"].capitalize(),
            "icon": data["weather"][0]["icon"]
        }
    except: return {}

@app.route("/api/sales")
def api_sales():
    global CACHE,CACHE_TS
    if time.time()-CACHE_TS>60:
        today=fetch_category_sales(0,cut_to_now=True)
        prev=fetch_category_sales(7,cut_to_now=True)
        hourly=fetch_transactions_hourly(0)
        prev_hourly=fetch_transactions_hourly(7)
        weather=fetch_weather()
        CACHE={"hot":today["hot"],"cold":today["cold"],"bar":today["bar"],
               "hot_prev":prev["hot"],"cold_prev":prev["cold"],
               "hourly":hourly,"hourly_prev":prev_hourly,"weather":weather}
        CACHE_TS=time.time()
    return jsonify(CACHE)

@app.route("/")
def index():
    template="""
    <html>
    <head>
        <meta charset="utf-8"/>
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <style>
            body{margin:0;background:#0f0f0f;color:#eee;font-family:Arial,sans-serif}
            .wrap{padding:10px;display:flex;flex-direction:column;gap:10px;height:100vh;box-sizing:border-box}
            .top{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;flex:1}
            .bottom{flex:1}
            .card{background:#151515;border-radius:10px;padding:10px;overflow:hidden}
            table{width:100%;border-collapse:collapse;font-size:14px}
            th,td{padding:2px 6px;text-align:right}
            th:first-child,td:first-child{text-align:left}
            h2{margin:0 0 6px 0;font-size:16px}
            canvas{width:100%!important;height:100%!important}
        </style>
    </head>
    <body>
        <div class="wrap">
            <div class="top">
                <div class="card"><h2>🔥 Гарячий цех</h2><table id="hot_tbl"></table></div>
                <div class="card"><h2>❄️ Холодний цех</h2><table id="cold_tbl"></table></div>
                <div class="card"><h2>📊 Розподіл замовлень</h2><canvas id="pie"></canvas></div>
                <div class="card"><h2>🕒 Час і погода</h2>
                    <div style="font-size:24px" id="clock"></div>
                    <img id="wicon" style="width:50px;height:50px"/>
                    <div id="wtemp"></div><div id="wdesc"></div>
                </div>
            </div>
            <div class="card bottom"><h2>📈 Замовлення по годинах (накопич.)</h2><canvas id="line"></canvas></div>
        </div>
        <script>
        let lineChart,pieChart;
        function refresh(){
            fetch('/api/sales').then(r=>r.json()).then(data=>{
                function fill(id,today,prev){
                    let html="<tr><th>Категорія</th><th>Сьогодні</th><th>Мин. тиждень</th></tr>";
                    let keys=[...new Set([...Object.keys(today),...Object.keys(prev)])];
                    keys.forEach(k=>{
                        html+=`<tr><td>${k}</td><td>${today[k]||0}</td><td>${prev[k]||0}</td></tr>`;
                    });
                    document.getElementById(id).innerHTML=html;
                }
                fill('hot_tbl',data.hot,data.hot_prev);
                fill('cold_tbl',data.cold,data.cold_prev);
                let totHot=Object.values(data.hot).reduce((a,b)=>a+b,0),
                    totCold=Object.values(data.cold).reduce((a,b)=>a+b,0),
                    totBar=Object.values(data.bar).reduce((a,b)=>a+b,0);
                let ctxp=document.getElementById('pie').getContext('2d');
                if(pieChart) pieChart.destroy();
                pieChart=new Chart(ctxp,{type:'pie',
                    data:{labels:[`Гарячий ${Math.round(totHot/(totHot+totCold+totBar)*100)}%`,
                                  `Холодний ${Math.round(totCold/(totHot+totCold+totBar)*100)}%`,
                                  `Бар ${Math.round(totBar/(totHot+totCold+totBar)*100)}%`],
                          datasets:[{data:[totHot,totCold,totBar],backgroundColor:['#ff8800','#33b5ff','#9b59b6']}]},
                    options:{plugins:{legend:{display:false},tooltip:{enabled:false}}}
                });
                let now=new Date(),curHour=now.getHours();
                let cutIdx=data.hourly.labels.findIndex(l=>parseInt(l)>curHour);
                if(cutIdx==-1)cutIdx=data.hourly.labels.length;
                let today={labels:data.hourly.labels.slice(0,cutIdx),hot:data.hourly.hot.slice(0,cutIdx),cold:data.hourly.cold.slice(0,cutIdx)};
                let ctx=document.getElementById('line').getContext('2d');
                if(lineChart) lineChart.destroy();
                lineChart=new Chart(ctx,{type:'line',
                    data:{labels:data.hourly.labels,
                          datasets:[{label:'Гарячий',data:today.hot,borderColor:'#ff8800',backgroundColor:'#ff8800'},
                                    {label:'Холодний',data:today.cold,borderColor:'#33b5ff',backgroundColor:'#33b5ff'},
                                    {label:'Гарячий (мин. тижд.)',data:data.hourly_prev.hot,borderColor:'#ff8800',borderDash:[6,3]},
                                    {label:'Холодний (мин. тижд.)',data:data.hourly_prev.cold,borderColor:'#33b5ff',borderDash:[6,3]}]},
                    options:{responsive:true,maintainAspectRatio:false,
                             plugins:{legend:{labels:{color:'#fff'}}},
                             scales:{x:{ticks:{color:'#bbb'}},y:{ticks:{color:'#bbb'},beginAtZero:true}}}});
                if(data.weather){
                    document.getElementById('clock').innerText=new Date().toLocaleTimeString('uk-UA',{hour:'2-digit',minute:'2-digit'});
                    document.getElementById('wicon').src="http://openweathermap.org/img/wn/"+data.weather.icon+"@2x.png";
                    document.getElementById('wtemp').innerText=data.weather.temp+"°C";
                    document.getElementById('wdesc').innerText=data.weather.desc;
                }
            });
        }
        refresh();setInterval(refresh,60000);
        </script>
    </body>
    </html>
    """
    return render_template_string(template)

if __name__=="__main__":
    app.run(host="0.0.0.0",port=int(os.getenv("PORT",5000)))
