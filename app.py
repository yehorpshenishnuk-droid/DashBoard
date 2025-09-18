import os
import time
import requests
from datetime import date, datetime, timedelta
from flask import Flask, render_template_string, jsonify

app = Flask(__name__)

# ==== Конфиг ====
ACCOUNT_NAME    = "poka-net3"
POSTER_TOKEN    = os.getenv("POSTER_TOKEN")  # обязательный
OPENWEATHER_KEY = "8691b318dac1b04215b2271ae720310"  # твой ключ

# Координаты: Софіївська Борщагівка
LAT, LON = 50.395, 30.355

# Категории POS ID
HOT_CATEGORIES  = {4, 13, 15, 46, 33}                      # 🔥 Гарячий цех
COLD_CATEGORIES = {7, 8, 11, 16, 18, 19, 29, 32, 36, 44}   # ❄️ Холодний цех
BAR_CATEGORIES  = {9, 14, 27, 28, 34, 41, 42, 47, 22, 24, 25, 26, 39, 30}  # 🍸 Бар

# Кэши
PRODUCT_CACHE = {}
PRODUCT_CACHE_TS = 0
CACHE = {}
CACHE_TS = 0


def _get(url, timeout=25):
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    return r


# ===== справочник товаров (product_id -> menu_category_id)
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
                data = _get(url).json().get("response", [])
            except Exception:
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
    return PRODUCT_CACHE


# ===== сводные продажи по категориям за дату
def fetch_category_sales(target_date):
    url = (
        f"https://{ACCOUNT_NAME}.joinposter.com/api/dash.getCategoriesSales"
        f"?token={POSTER_TOKEN}&dateFrom={target_date}&dateTo={target_date}"
    )
    try:
        rows = _get(url).json().get("response", [])
    except Exception:
        return {"hot": {}, "cold": {}, "bar": {}}

    hot, cold, bar = {}, {}, {}
    for row in rows:
        try:
            cid  = int(row.get("category_id", 0))
            name = (row.get("category_name") or "").strip()
            qty  = int(float(row.get("count", 0)))
        except Exception:
            continue
        if cid in HOT_CATEGORIES:
            hot[name] = hot.get(name, 0) + qty
        elif cid in COLD_CATEGORIES:
            cold[name] = cold.get(name, 0) + qty
        elif cid in BAR_CATEGORIES:
            bar[name] = bar.get(name, 0) + qty
    return {"hot": hot, "cold": cold, "bar": bar}


# ===== почасовые накопленные данные (для графика)
def fetch_transactions_hourly(day_offset=0):
    products = load_products()
    target_date = (date.today() - timedelta(days=day_offset)).strftime("%Y-%m-%d")

    per_page = 500
    page = 1
    hours = list(range(10, 23))
    hot_by_hour  = [0] * len(hours)
    cold_by_hour = [0] * len(hours)

    while True:
        url = (
            f"https://{ACCOUNT_NAME}.joinposter.com/api/transactions.getTransactions"
            f"?token={POSTER_TOKEN}&date_from={target_date}&date_to={target_date}"
            f"&per_page={per_page}&page={page}"
        )
        try:
            body  = _get(url).json().get("response", {}) or {}
            items = body.get("data", []) or []
            total = int(body.get("count", 0) or 0)
            page_info = body.get("page", {}) or {}
            per_page_resp = int(page_info.get("per_page", per_page) or per_page)
        except Exception:
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

    # кумулятив
    hot_cum, cold_cum = [], []
    th = tc = 0
    for h, c in zip(hot_by_hour, cold_by_hour):
        th += h; tc += c
        hot_cum.append(th)
        cold_cum.append(tc)

    labels = [f"{h:02d}:00" for h in hours]  # 10:00..22:00 — всегда полный набор
    return {"labels": labels, "hot": hot_cum, "cold": cold_cum}


# ===== погода (OpenWeather)
def fetch_weather():
    try:
        url = (
            f"https://api.openweathermap.org/data/2.5/weather"
            f"?lat={LAT}&lon={LON}&appid={OPENWEATHER_KEY}&units=metric&lang=uk"
        )
        data = _get(url, timeout=15).json()
        temp = round(float(data["main"]["temp"]))
        desc = str(data["weather"][0]["description"]).capitalize()
        icon = str(data["weather"][0]["icon"])  # напр. "10d"
        return {"temp": temp, "desc": desc, "icon": icon}
    except Exception:
        # надёжный фоллбек
        return {"temp": "—", "desc": "Н/Д", "icon": "01d"}


# ===== API =====
@app.route("/api/sales")
def api_sales():
    global CACHE, CACHE_TS
    if time.time() - CACHE_TS > 60:
        today    = date.today().strftime("%Y-%m-%d")
        week_ago = (date.today() - timedelta(days=7)).strftime("%Y-%m-%d")

        sums_today = fetch_category_sales(today)
        sums_prev  = fetch_category_sales(week_ago)

        total_hot  = sum(sums_today["hot"].values())
        total_cold = sum(sums_today["cold"].values())
        total_bar  = sum(sums_today["bar"].values())
        total = total_hot + total_cold + total_bar
        shares = {}
        if total > 0:
            shares = {
                "hot":  round(total_hot  / total * 100),
                "cold": round(total_cold / total * 100),
                "bar":  round(total_bar  / total * 100),
            }

        hourly = fetch_transactions_hourly(0)
        prev   = fetch_transactions_hourly(7)
        weather = fetch_weather()

        CACHE = {
            "hot": sums_today["hot"], "cold": sums_today["cold"], "bar": sums_today["bar"],
            "hot_prev": sums_prev["hot"], "cold_prev": sums_prev["cold"],
            "shares": shares,
            "hourly": hourly, "hourly_prev": prev,
            "weather": weather
        }
        CACHE_TS = time.time()
    return jsonify(CACHE)


# ===== UI =====
@app.route("/")
def index():
    template = """
<!doctype html>
<html>
<head>
<meta charset="utf-8" />
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-datalabels@2"></script>
<style>
:root { --bg:#0f0f0f; --panel:#151515; --fg:#eee; --hot:#ff8800; --cold:#33b5ff; --bar:#9b59b6; }
body{margin:0;background:var(--bg);color:var(--fg);font-family:Inter,Arial,sans-serif;font-size:14px}
.wrap{padding:10px;height:100vh;display:grid;grid-template-rows:45% 55%;gap:10px}
.top{display:grid;grid-template-columns:1fr 1fr 0.7fr 0.6fr;gap:10px}
.card{background:var(--panel);border-radius:10px;padding:8px 10px;overflow:hidden}
h2{font-size:16px;margin:0 0 6px 0}
.table{display:grid;grid-template-columns:62% 19% 19%;gap:2px;font-size:13px}
.table div{padding:1px 2px}
.head{color:#aaa;font-weight:600;border-bottom:1px solid #333}
.right{text-align:right}
.chartBox{position:relative;width:100%;height:calc(100% - 30px)} /* минус заголовок */
.pieWrap{position:relative;width:100%;height:calc(100% - 30px);display:flex;align-items:center;justify-content:center}
.pieWrap canvas{max-width:100%;max-height:100%}
.weather{display:flex;flex-direction:column;align-items:center;justify-content:center;height:calc(100% - 30px);text-align:center}
.weather .time{font-size:24px;font-weight:700;margin-bottom:6px}
.weather img{width:64px;height:64px;image-rendering:crisp-edges}
.weather .temp{font-size:20px;font-weight:700;margin-top:6px}
.weather .desc{font-size:14px;color:#ccc}
.logo{position:fixed;right:12px;bottom:8px;font-weight:800;font-size:12px}
</style>
</head>
<body>
  <div class="wrap">
    <div class="top">
      <div class="card"><h2>🔥 Гарячий цех</h2><div id="hot_tbl" class="table"></div></div>
      <div class="card"><h2>❄️ Холодний цех</h2><div id="cold_tbl" class="table"></div></div>
      <div class="card">
        <h2>📊 Розподіл замовлень</h2>
        <div class="pieWrap"><canvas id="pie"></canvas></div>
      </div>
      <div class="card">
        <h2>🕒 Час і погода</h2>
        <div class="weather">
          <div class="time" id="time">--:--</div>
          <img id="wicon" alt="weather icon" />
          <div class="temp" id="wtemp">—°C</div>
          <div class="desc" id="wdesc">Н/Д</div>
        </div>
      </div>
    </div>

    <div class="card">
      <h2>📈 Замовлення по годинах (накопич.)</h2>
      <div class="chartBox"><canvas id="chart"></canvas></div>
    </div>
  </div>
  <div class="logo">GRECO</div>

<script>
let chart, pie;

function cutToNow(labels, hot, cold){
  const now = new Date();
  const curHour = now.getHours();
  let cutIndex = labels.findIndex(l => parseInt(l) > curHour);
  if(cutIndex === -1) cutIndex = labels.length;
  return { labels: labels.slice(0, cutIndex), hot: hot.slice(0, cutIndex), cold: cold.slice(0, cutIndex) };
}

function updateClock(){
  const now = new Date();
  document.getElementById("time").innerText = now.toLocaleTimeString("uk-UA",{hour:"2-digit",minute:"2-digit"});
}

async function refresh(){
  const r = await fetch('/api/sales');
  const data = await r.json();

  // ===== таблицы
  function fill(id, todayObj, prevObj){
    const el = document.getElementById(id);
    let html = "<div class='head'>Категорія</div><div class='head right'>Сьогодні</div><div class='head right'>Мин. тиждень</div>";
    const keys = new Set([...Object.keys(todayObj), ...Object.keys(prevObj)]);
    keys.forEach(k => { html += `<div>${k}</div><div class='right'>${todayObj[k]||0}</div><div class='right'>${prevObj[k]||0}</div>`; });
    if(keys.size===0) html += "<div>—</div><div class='right'>0</div><div class='right'>0</div>";
    el.innerHTML = html;
  }
  fill('hot_tbl',  data.hot  || {}, data.hot_prev  || {});
  fill('cold_tbl', data.cold || {}, data.cold_prev || {});

  // ===== круговая (без легенды, с подписями внутри)
  const ctxPie = document.getElementById('pie').getContext('2d');
  if(pie) pie.destroy();
  pie = new Chart(ctxPie, {
    type: 'pie',
    data: {
      labels: ['Бар','Гарячий','Холодний'],
      datasets: [{ data:[data.shares.bar||0, data.shares.hot||0, data.shares.cold||0],
                   backgroundColor:['#9b59b6','#ff8800','#33b5ff'],
                   borderColor: '#1e1e1e', borderWidth: 2 }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      aspectRatio: 1,
      plugins: {
        legend: { display:false },
        datalabels: {
          color:'#fff',
          formatter:(value, ctx)=> ctx.chart.data.labels[ctx.dataIndex] + ' ' + value + '%',
          font: { weight: '700' }
        }
      },
      layout: { padding: 0 }
    },
    plugins:[ChartDataLabels]
  });

  // ===== график по часам
  const todayCut = cutToNow(data.hourly.labels, data.hourly.hot, data.hourly.cold);
  const prev     = data.hourly_prev;
  const ctx = document.getElementById('chart').getContext('2d');
  if(chart) chart.destroy();
  chart = new Chart(ctx,{
    type:'line',
    data:{
      // ось X — всегда полный набор 10:00..22:00
      labels: data.hourly.labels,
      datasets:[
        {label:'Гарячий', data:todayCut.hot,  borderColor:'#ff8800', tension:0.25, fill:false},
        {label:'Холодний', data:todayCut.cold, borderColor:'#33b5ff', tension:0.25, fill:false},
        {label:'Гарячий (мин. тижд.)', data:prev.hot,  borderColor:'#ff8800', borderDash:[6,4], tension:0.25, fill:false},
        {label:'Холодний (мин. тижд.)', data:prev.cold, borderColor:'#33b5ff', borderDash:[6,4], tension:0.25, fill:false}
      ]
    },
    options:{
      maintainAspectRatio:false,
      animation:false,
      plugins:{ legend:{ labels:{ color:'#ddd' } } },
      scales:{
        x:{
          type:'category',
          ticks:{ color:'#bbb', autoSkip:false, maxRotation:0, font:{size:12} },
          grid:{ color:'rgba(255,255,255,0.08)' }
        },
        y:{
          beginAtZero:true,
          ticks:{ color:'#bbb', font:{size:12} },
          grid:{ color:'rgba(255,255,255,0.08)' }
        }
      }
    }
  });

  // ===== погода
  const w = data.weather || {};
  document.getElementById("wtemp").innerText = (w.temp is not None and w.temp != '—') ? (w.temp + "°C") : "—°C";
  document.getElementById("wdesc").innerText = w.desc || "Н/Д";
  const icon = w.icon || "01d";
  document.getElementById("wicon").src = "https://openweathermap.org/img/wn/" + icon + "@2x.png";
}

updateClock(); setInterval(updateClock, 60000);
refresh(); setInterval(refresh, 60000);
</script>
</body>
</html>
    """
    return render_template_string(template)


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
