import os
import time
import sys
import math
import logging
import requests
from datetime import date, datetime, timedelta
from flask import Flask, jsonify, render_template_string

app = Flask(__name__)
logging.basicConfig(level=logging.DEBUG, stream=sys.stderr, format="%(asctime)s %(levelname)s %(message)s")

# ========= ENV / CONFIG =========
POSTER_ACCOUNT   = os.getenv("POSTER_ACCOUNT", "poka-net3")
POSTER_TOKEN     = os.getenv("POSTER_TOKEN")            # обязателен
CHOICE_TOKEN     = os.getenv("CHOICE_TOKEN")            # обязателен (Bearer)
CHOICE_BASE_URL  = os.getenv("CHOICE_BASE_URL", "https://open-api.choiceqr.com/api")

# Категории POS ID
HOT_CATEGORIES  = {4, 13, 15, 46, 33}
COLD_CATEGORIES = {7, 8, 11, 16, 18, 19, 29, 32, 36, 44}

# Кэши
PRODUCT_CACHE = {}        # product_id -> menu_category_id
PRODUCT_CACHE_TS = 0
CACHE = {"hot": {}, "cold": {}, "hourly": {}, "hourly_prev": {}, "bookings": []}
CACHE_TS = 0

# ========= Helpers =========
def http_get(url, *, params=None, headers=None, timeout=25, log_body=True):
    r = requests.get(url, params=params, headers=headers, timeout=timeout)
    body = r.text[:1500].replace("\n", " ") if log_body else f"<{len(r.text)} bytes>"
    logging.debug(f"GET {r.url} -> {r.status_code} : {body}")
    r.raise_for_status()
    return r

def rate_limited_get(url, *, params=None, headers=None, timeout=25, retries=2, backoff=10):
    """Повтор на 429 (rate limit)."""
    for attempt in range(retries + 1):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=timeout)
            body = r.text[:500].replace("\n", " ")
            logging.debug(f"GET {r.url} -> {r.status_code} : {body}")
            if r.status_code == 429 and attempt < retries:
                time.sleep(backoff)
                continue
            r.raise_for_status()
            return r
        except requests.HTTPError as e:
            if getattr(e.response, "status_code", None) == 429 and attempt < retries:
                time.sleep(backoff)
                continue
            raise

# ========= Products directory (Poster) =========
def load_products():
    global PRODUCT_CACHE, PRODUCT_CACHE_TS
    if PRODUCT_CACHE and time.time() - PRODUCT_CACHE_TS < 3600:
        return PRODUCT_CACHE

    mapping = {}
    per_page = 500
    for ptype in ("products", "batchtickets"):
        page = 1
        while True:
            url = f"https://{POSTER_ACCOUNT}.joinposter.com/api/menu.getProducts"
            params = {"token": POSTER_TOKEN, "type": ptype, "per_page": per_page, "page": page}
            try:
                resp = http_get(url, params=params)
                data = resp.json().get("response", [])
            except Exception as e:
                logging.error(f"load_products error: {e}")
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
    logging.debug(f"products cached: {len(PRODUCT_CACHE)}")
    return PRODUCT_CACHE

# ========= Category sales today (Poster) =========
def fetch_category_sales():
    today = date.today().strftime("%Y-%m-%d")
    url = f"https://{POSTER_ACCOUNT}.joinposter.com/api/dash.getCategoriesSales"
    params = {"token": POSTER_TOKEN, "dateFrom": today, "dateTo": today}
    try:
        resp = http_get(url, params=params)
        rows = resp.json().get("response", [])
    except Exception as e:
        logging.error(f"fetch_category_sales error: {e}")
        return {"hot": {}, "cold": {}}

    hot, cold = {}, {}
    for row in rows:
        try:
            cid = int(row.get("category_id", 0))
            name = str(row.get("category_name", "")).strip()
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

# ========= Hourly cumulative (Poster) =========
def fetch_transactions_hourly(day_offset=0):
    products = load_products()
    target_date = (date.today() - timedelta(days=day_offset)).strftime("%Y-%m-%d")

    per_page = 500
    page = 1
    hours = list(range(10, 23))  # 10:00–22:00
    hot_by_hour = [0] * len(hours)
    cold_by_hour = [0] * len(hours)

    while True:
        url = f"https://{POSTER_ACCOUNT}.joinposter.com/api/transactions.getTransactions"
        params = {
            "token": POSTER_TOKEN,
            "date_from": target_date,
            "date_to": target_date,
            "per_page": per_page,
            "page": page,
        }
        try:
            resp = http_get(url, params=params)
            body = resp.json().get("response", {})
            items = body.get("data", []) or []
            total = int(body.get("count", 0))
            page_info = body.get("page", {}) or {}
            per_page_resp = int(page_info.get("per_page", per_page) or per_page)
        except Exception as e:
            logging.error(f"transactions error: {e}")
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

    # cumulative
    hot_cum, cold_cum = [], []
    th = tc = 0
    for h, c in zip(hot_by_hour, cold_by_hour):
        th += h
        tc += c
        hot_cum.append(th)
        cold_cum.append(tc)

    labels = [f"{h:02d}:00" for h in hours]
    return {"labels": labels, "hot": hot_cum, "cold": cold_cum}

# ========= Bookings today (Choice Open API) =========
def fetch_bookings():
    if not CHOICE_TOKEN:
        return []
    url = f"{CHOICE_BASE_URL}/booking/list"
    today = datetime.utcnow().date()
    start = datetime.combine(today, datetime.min.time())
    end = datetime.combine(today, datetime.max.time())
    params = {
        "from": start.isoformat() + "Z",
        "till": end.isoformat() + "Z",
        "periodField": "dateTime",
        "page": 1,
        "perPage": 20,
    }
    headers = {"Authorization": f"Bearer {CHOICE_TOKEN}"}

    try:
        # retry on 429
        resp = rate_limited_get(url, params=params, headers=headers, timeout=25, retries=2, backoff=10)
        data = resp.json()
    except Exception as e:
        logging.error(f"Choice fetch error: {e}")
        return []

    # разные варианты обёртки
    items = data.get("items") or data.get("data") or data.get("list") or data.get("bookings") or []
    out = []
    for b in items[:12]:
        customer = b.get("customer") or {}
        name = customer.get("name") or b.get("name") or "—"
        guests = b.get("personCount") or b.get("persons") or b.get("guests") or "—"
        t = b.get("dateTime") or b.get("startDateTime") or b.get("bookingDt") or ""
        if isinstance(t, str) and len(t) >= 16:
            try:
                t = datetime.fromisoformat(t.replace("Z", "+00:00")).strftime("%H:%M")
            except Exception:
                try:
                    t = datetime.strptime(t, "%Y-%m-%d %H:%M:%S").strftime("%H:%M")
                except Exception:
                    pass
        out.append({"name": name, "time": t or "—", "guests": guests})
    return out

# ========= API =========
@app.route("/api/sales")
def api_sales():
    global CACHE, CACHE_TS
    # кэш 60с
    if time.time() - CACHE_TS > 60:
        sums = fetch_category_sales()
        today = fetch_transactions_hourly(0)
        prev = fetch_transactions_hourly(7)
        bookings = fetch_bookings()
        CACHE.update({
            "hot": sums["hot"], "cold": sums["cold"],
            "hourly": today, "hourly_prev": prev,
            "bookings": bookings
        })
        CACHE_TS = time.time()
    return jsonify(CACHE)

# ========= UI =========
@app.route("/")
def index():
    template = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
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
    .card{background:var(--panel);border-radius:14px;padding:14px 16px;outline:3px solid rgba(255,255,255,0.04);box-shadow:0 0 22px rgba(0,0,0,0.45)}
    .card.hot{ outline-color:rgba(255,136,0,0.45) }
    .card.cold{ outline-color:rgba(51,181,255,0.45) }
    .card.book{ outline-color:rgba(0,212,106,0.45) }
    .card.chart{ grid-column:1/-1; outline-color:rgba(255,176,0,0.55) }
    h2{margin:4px 0 10px 0;font-size:26px;display:flex;align-items:center;gap:8px}
    table{width:100%;border-collapse:collapse;font-size:18px}
    td{padding:4px 2px}
    td:last-child{text-align:right}
    .logo{position:fixed;right:18px;bottom:12px;font-weight:800;letter-spacing:.5px}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="row">
      <div class="card hot"><h2>🔥 Гарячий цех</h2><table id="hot_tbl"></table></div>
      <div class="card cold"><h2>❄️ Холодний цех</h2><table id="cold_tbl"></table></div>
      <div class="card book"><h2>📅 Бронювання</h2><table id="book_tbl"></table></div>
      <div class="card chart"><h2>📊 Замовлення по годинах (накопич.)</h2><canvas id="chart" height="160"></canvas></div>
    </div>
  </div>
  <div class="logo">GRECO</div>

  <script>
  let chart;

  function cutToNow(labels, arr){
    const now = new Date();
    const curHour = now.getHours();
    let cutIndex = labels.findIndex(l => parseInt(l) > curHour);
    if(cutIndex === -1) cutIndex = labels.length;
    return arr.slice(0, cutIndex);
  }

  // Дополняем массив до длины labels последним значением (для пунктирных прошлой недели)
  function padToLabels(labels, arr){
    const out = arr.slice();
    while(out.length < labels.length){
      out.push(out.length ? out[out.length-1] : 0);
    }
    return out.slice(0, labels.length);
  }

  async function refresh(){
    const r = await fetch('/api/sales');
    const data = await r.json();

    const fill = (id, obj) => {
      const el = document.getElementById(id);
      let html = "";
      Object.entries(obj||{}).forEach(([k,v]) => html += `<tr><td>${k}</td><td>${v}</td></tr>`);
      if(!html) html = "<tr><td>—</td><td>0</td></tr>";
      el.innerHTML = html;
    };
    fill('hot_tbl', data.hot);
    fill('cold_tbl', data.cold);

    const b = document.getElementById('book_tbl');
    b.innerHTML = (data.bookings||[]).map(x => `<tr><td>${x.name}</td><td>${x.time}</td><td>${x.guests}</td></tr>`).join('') || "<tr><td>—</td><td></td><td></td></tr>";

    const labels = (data.hourly&&data.hourly.labels)||[];
    const tHot = cutToNow(labels, (data.hourly&&data.hourly.hot)||[]);
    const tCold= cutToNow(labels, (data.hourly&&data.hourly.cold)||[]);
    const pHot = padToLabels(labels, (data.hourly_prev&&data.hourly_prev.hot)||[]);
    const pCold= padToLabels(labels, (data.hourly_prev&&data.hourly_prev.cold)||[]);

    const ctx = document.getElementById('chart').getContext('2d');
    if(chart) chart.destroy();
    chart = new Chart(ctx,{
      type:'line',
      data:{
        labels: labels, // фиксированная ось 10:00–22:00
        datasets:[
          {label:'Гарячий', data:tHot,  borderColor:'#ff8800', backgroundColor:'#ff8800', tension:0.25, fill:false},
          {label:'Холодний', data:tCold, borderColor:'#33b5ff', backgroundColor:'#33b5ff', tension:0.25, fill:false},
          {label:'Гарячий (мин. тижд.)', data:pHot, borderColor:'#ff8800', borderDash:[6,4], tension:0.25, fill:false},
          {label:'Холодний (мин. тижд.)', data:pCold, borderColor:'#33b5ff', borderDash:[6,4], tension:0.25, fill:false}
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
