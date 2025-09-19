import os
import requests
import sys
from flask import Flask, render_template_string, jsonify

app = Flask(__name__)

# ==== Конфиг ====
ACCOUNT_NAME = "poka-net3"
POSTER_TOKEN = os.getenv("POSTER_TOKEN")           # обязателен

# ====== Столы ======
ALL_TABLES = {
    1:"Стол 1", 2:"Стол 2", 3:"Стол 3", 4:"Стол 4", 5:"Стол 5", 6:"Стол 6",
    7:"Стол 7", 10:"Стол 10", 11:"Стол 11", 12:"Стол 12", 13:"Стол 13"
}
TERRACE_IDS = {7, 10, 11, 12, 13}

# ===== Helpers =====
def _get(url, **kwargs):
    r = requests.get(url, timeout=kwargs.pop("timeout", 25))
    log_snippet = r.text[:200].replace("\n", " ")
    print(f"DEBUG GET {url.split('?')[0]} -> {r.status_code} : {log_snippet}", file=sys.stderr, flush=True)
    r.raise_for_status()
    return r

# ===== API Poster: открытые заказы =====
def fetch_open_orders():
    url = f"https://{ACCOUNT_NAME}.joinposter.com/api/dash.getOpenOrders?token={POSTER_TOKEN}"
    try:
        resp = _get(url)
        rows = resp.json().get("response", [])
    except Exception as e:
        print("ERROR open_orders:", e, file=sys.stderr, flush=True)
        return {}

    busy = {}
    for row in rows:
        try:
            tid = int(row.get("table_id", 0))
            waiter = row.get("user_name", "").strip()
            if tid:
                busy[tid] = waiter
        except Exception:
            continue
    return busy

# ===== Новый эндпоинт для зал/тераса =====
@app.route("/api/tables")
def api_tables():
    busy = fetch_open_orders()

    hall, terrace = [], []
    for tid, name in ALL_TABLES.items():
        table_info = {
            "id": tid,
            "name": name,
            "status": "busy" if tid in busy else "free",
            "waiter": busy.get(tid, "")
        }
        if tid in TERRACE_IDS:
            terrace.append(table_info)
        else:
            hall.append(table_info)

    return jsonify({"hall": hall, "terrace": terrace})

# ===== UI =====
@app.route("/")
def index():
    template = """
    <html>
    <head>
        <meta charset="utf-8" />
        <style>
            :root {
                --bg:#0f0f0f; --panel:#151515; --fg:#eee;
                --free:#444; --busy:#3498db;
            }
            body{margin:0;background:var(--bg);color:var(--fg);font-family:Inter,Arial,sans-serif}
            .wrap{padding:10px;max-width:1200px;margin:0 auto}
            .card{background:var(--panel);border-radius:12px;padding:10px 14px;margin-bottom:12px}
            .tables{display:grid;grid-template-columns:repeat(6,1fr);gap:10px;margin-bottom:15px}
            .table{border-radius:8px;padding:16px;text-align:center;font-weight:bold}
            .table.free{background:var(--free);color:#ccc;}
            .table.busy{background:var(--busy);color:#fff;}
            .table small{display:block;font-weight:normal;font-size:14px;margin-top:6px}
            h2{margin:5px 0 10px;font-size:20px}
            h3{margin:10px 0 5px;font-size:18px;color:#bbb}
        </style>
    </head>
    <body>
        <div class="wrap">
            <div class="card hall">
                <h2>🪑 Зал</h2>
                <h3>Основний зал</h3>
                <div id="hall_grid"></div>
                <h3>Літня тераса</h3>
                <div id="terrace_grid"></div>
            </div>
        </div>
        <script>
        async function loadTables(){
            const r = await fetch('/api/tables');
            const data = await r.json();

            function renderTables(list, target){
                let html = '<div class="tables">';
                list.forEach(t=>{
                    const cls = t.status === 'busy' ? 'busy' : 'free';
                    html += `<div class="table ${cls}">
                               <div>${t.name}</div>
                               <small>${t.waiter||''}</small>
                             </div>`;
                });
                html += '</div>';
                document.getElementById(target).innerHTML = html;
            }

            renderTables(data.hall, 'hall_grid');
            renderTables(data.terrace, 'terrace_grid');
        }

        loadTables(); setInterval(loadTables, 60000);
        </script>
    </body>
    </html>
    """
    return render_template_string(template)

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
