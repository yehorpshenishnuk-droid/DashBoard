import os
import time
import requests
import sys
from datetime import date, datetime, timedelta
from flask import Flask, render_template_string, jsonify

app = Flask(__name__)

# ==== Конфіг ====
ACCOUNT_NAME = "poka-net3"
POSTER_TOKEN = os.getenv("POSTER_TOKEN")
CHOICE_TOKEN = os.getenv("CHOICE_TOKEN")
WEATHER_KEY = os.getenv("WEATHER_KEY", "")
POWER_ADDRESS = os.getenv("POWER_ADDRESS", "3.2")  # Адреса для перевірки світла

# Категорії POS ID
HOT_CATEGORIES  = {4, 13, 15, 46, 33}
COLD_CATEGORIES = {7, 8, 11, 16, 18, 19, 29, 32, 36, 44}
BAR_CATEGORIES  = {9,14,27,28,34,41,42,47,22,24,25,26,39,30}

# Кеш
PRODUCT_CACHE = {}
PRODUCT_CACHE_TS = 0
CACHE = {
    "hot": {}, "cold": {}, "hot_prev": {}, "cold_prev": {},
    "hourly": {}, "hourly_prev": {}, "hourly_year": {}, "share": {}
}
CACHE_TS = 0

BOOKINGS_CACHE = []
BOOKINGS_CACHE_TS = 0

# ===== Helpers =====
def _get(url, **kwargs):
    r = requests.get(url, timeout=kwargs.pop("timeout", 25))
    log_snippet = r.text[:500].replace("\n", " ")
    print(f"DEBUG GET {url.split('?')[0]} -> {r.status_code} : {log_snippet}", file=sys.stderr, flush=True)
    r.raise_for_status()
    return r

# ===== Довідник товарів =====
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

# ===== Зведені продажі =====
def fetch_category_sales(day_offset=0):
    target_date = (date.today() - timedelta(days=day_offset)).strftime("%Y-%m-%d")
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

    hot = dict(sorted(hot.items(), key=lambda x: x[0]))
    cold = dict(sorted(cold.items(), key=lambda x: x[0]))
    bar = dict(sorted(bar.items(), key=lambda x: x[0]))
    return {"hot": hot, "cold": cold, "bar": bar}

# ===== Функція для отримання даних по конкретній даті =====
def fetch_transactions_hourly_for_date(target_date_str):
    products = load_products()
    
    per_page = 500
    page = 1
    hours = list(range(10, 23))
    hot_by_hour = [0] * len(hours)
    cold_by_hour = [0] * len(hours)

    while True:
        url = (
            f"https://{ACCOUNT_NAME}.joinposter.com/api/transactions.getTransactions"
            f"?token={POSTER_TOKEN}&date_from={target_date_str}&date_to={target_date_str}"
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
            print(f"ERROR transactions for {target_date_str}:", e, file=sys.stderr, flush=True)
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
        th += h
        tc += c
        hot_cum.append(th)
        cold_cum.append(tc)

    labels = [f"{h:02d}:00" for h in hours]
    return {"labels": labels, "hot": hot_cum, "cold": cold_cum}

# ===== Почасова діаграма =====
def fetch_transactions_hourly(day_offset=0):
    target_date = (date.today() - timedelta(days=day_offset)).strftime("%Y-%m-%d")
    return fetch_transactions_hourly_for_date(target_date)

# ===== Отримання даних рік назад по дню тижня =====
def fetch_transactions_hourly_year_ago():
    today = date.today()
    today_weekday = today.weekday()
    
    year_ago = today - timedelta(days=365)
    year_ago_weekday = year_ago.weekday()
    day_diff = today_weekday - year_ago_weekday
    year_ago_same_weekday = year_ago + timedelta(days=day_diff)
    
    target_date_str = year_ago_same_weekday.strftime("%Y-%m-%d")
    print(f"DEBUG: Year ago same weekday: {target_date_str} ({year_ago_same_weekday.strftime('%A')})", file=sys.stderr, flush=True)
    
    return fetch_transactions_hourly_for_date(target_date_str)

# ===== Погода =====
def fetch_weather():
    if not WEATHER_KEY:
        return {"temp": "Н/Д", "desc": "Н/Д", "icon": ""}
    try:
        url = f"https://api.openweathermap.org/data/2.5/weather?lat=50.395&lon=30.355&appid={WEATHER_KEY}&units=metric&lang=uk"
        resp = requests.get(url, timeout=10)
        data = resp.json()
        temp = round(data["main"]["temp"])
        desc = data["weather"][0]["description"].capitalize()
        icon = data["weather"][0]["icon"]
        return {"temp": f"{temp}°C", "desc": desc, "icon": icon}
    except Exception as e:
        print("ERROR weather:", e, file=sys.stderr, flush=True)
        return {"temp": "Н/Д", "desc": "Н/Д", "icon": ""}

# ===== Відключення світла =====
POWER_CACHE = {"status": "—", "next": "", "has_power": None, "icon": "❓", "schedule": []}
POWER_CACHE_TS = 0
POWER_GROUP = "3.2"  # Ваша група (Софіївська Борщагівка, вул. Миру 36)
# Для Києва: region_id=25, dso_id=902

def fetch_power_status():
    """
    Отримує графік відключень для групи 3.2 (Софіївська Борщагівка).
    Використовує кілька альтернативних API для надійності.
    """
    global POWER_CACHE, POWER_CACHE_TS
    
    # Кеш на 5 хвилин
    if time.time() - POWER_CACHE_TS < 300:
        return POWER_CACHE
    
    print(f"DEBUG: Fetching power status for group {POWER_GROUP}...", file=sys.stderr, flush=True)
    
    # Список API для спроби (від найкращого до запасних)
    api_sources = [
        {
            "name": "Yasno Direct",
            "url": "https://app.yasno.ua/api/blackout-service/public/shutdowns/regions/25/dsos/902/planned-outages",
            "parser": "yasno_new"
        },
        {
            "name": "Yasno via CORS Proxy",
            "url": "https://corsproxy.io/?https://app.yasno.ua/api/blackout-service/public/shutdowns/regions/25/dsos/902/planned-outages",
            "parser": "yasno_new"
        },
        {
            "name": "Alternative API",
            "url": "https://api.allorigins.win/raw?url=https://app.yasno.ua/api/blackout-service/public/shutdowns/regions/25/dsos/902/planned-outages",
            "parser": "yasno_new"
        }
    ]
    
    for api in api_sources:
        try:
            print(f"DEBUG: Trying {api['name']}...", file=sys.stderr, flush=True)
            
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json",
                "Accept-Language": "uk-UA,uk;q=0.9"
            }
            
            # Збільшуємо таймаут для free tier
            resp = requests.get(api["url"], headers=headers, timeout=20)
            print(f"DEBUG: {api['name']} status: {resp.status_code}", file=sys.stderr, flush=True)
            
            if resp.status_code != 200:
                print(f"DEBUG: Skipping {api['name']}, status {resp.status_code}", file=sys.stderr, flush=True)
                continue
            
            data = resp.json()
            
            # Парсимо відповідь
            result = parse_yasno_new_api(data, POWER_GROUP)
            if result:
                POWER_CACHE = result
                POWER_CACHE_TS = time.time()
                print(f"DEBUG: ✅ Success with {api['name']}: {POWER_CACHE}", file=sys.stderr, flush=True)
                return POWER_CACHE
            else:
                print(f"DEBUG: Parser returned None for {api['name']}", file=sys.stderr, flush=True)
                
        except requests.exceptions.Timeout:
            print(f"WARNING: {api['name']} timeout", file=sys.stderr, flush=True)
            continue
        except requests.exceptions.ConnectionError as e:
            print(f"WARNING: {api['name']} connection error: {e}", file=sys.stderr, flush=True)
            continue
        except Exception as e:
            print(f"ERROR {api['name']}: {e}", file=sys.stderr, flush=True)
            import traceback
            traceback.print_exc(file=sys.stderr)
            continue
    
    print(f"WARNING: All API sources failed", file=sys.stderr, flush=True)
    
    # Якщо всі API не працюють, але у нас є старий кеш - використовуємо його
    if POWER_CACHE and POWER_CACHE.get("status") and POWER_CACHE.get("status") != "—":
        print(f"DEBUG: Using cached data (age: {int(time.time() - POWER_CACHE_TS)}s)", file=sys.stderr, flush=True)
        return POWER_CACHE
    
    # Якщо немає жодних даних
    POWER_CACHE = {
        "status": "Дані недоступні",
        "next": "Перевірте yasno.com.ua",
        "has_power": None,
        "icon": "❓",
        "schedule": [],
        "schedule_text": "API тимчасово недоступне",
        "timeline": [],
        "current_minutes": 0
    }
    
    return POWER_CACHE

def parse_yasno_new_api(data, group="3.1"):
    """
    Парсить нове API Yasno (app.yasno.ua/api/blackout-service/)
    
    Формат: {
        "3.1": {
            "today": {
                "slots": [
                    {"start": 0, "end": 300, "type": "NotPlanned"},  # Хвилини від початку дня
                    {"start": 300, "end": 600, "type": "Definite"},  # Відключення 05:00-10:00
                    ...
                ],
                "date": "2026-02-06T00:00:00+02:00",
                "status": "ScheduleApplies"
            }
        }
    }
    """
    now = datetime.now()
    current_outage_end = None
    next_outage_start = None
    today_schedule = []
    all_slots_timeline = []  # Повний графік на день для візуалізації
    
    try:
        if group not in data:
            print(f"DEBUG: Group {group} not found in API response", file=sys.stderr, flush=True)
            # Спробуємо альтернативні формати групи
            for alt_group in [f"{group[0]}.{group[2]}", group.replace(".", "")]:
                if alt_group in data:
                    print(f"DEBUG: Found alternative group key: {alt_group}", file=sys.stderr, flush=True)
                    group = alt_group
                    break
            else:
                return None
        
        group_data = data[group]
        today_data = group_data.get("today", {})
        
        if not today_data or today_data.get("status") != "ScheduleApplies":
            print(f"DEBUG: No schedule applies for today", file=sys.stderr, flush=True)
            return {
                "status": "Є світло",
                "next": "Графік на сьогодні відсутній",
                "has_power": True,
                "icon": "🟢",
                "schedule": [],
                "schedule_text": "Графіків відключень немає",
                "timeline": [],
                "current_minutes": now.hour * 60 + now.minute
            }
        
        slots = today_data.get("slots", [])
        print(f"DEBUG: Found {len(slots)} time slots", file=sys.stderr, flush=True)
        
        # Поточний час у хвилинах від початку дня
        current_minutes = now.hour * 60 + now.minute
        
        # Обробляємо всі слоти
        for slot in slots:
            start_min = slot.get("start", 0)
            end_min = slot.get("end", 0)
            slot_type = slot.get("type", "")
            
            # Конвертуємо хвилини в час
            start_hour = start_min // 60
            start_minute = start_min % 60
            end_hour = end_min // 60
            end_minute = end_min % 60
            
            start_time = f"{start_hour:02d}:{start_minute:02d}"
            end_time = f"{end_hour:02d}:{end_minute:02d}"
            
            # Додаємо всі слоти в таймлайн для візуалізації
            all_slots_timeline.append({
                "start": start_time,
                "end": end_time,
                "start_min": start_min,
                "end_min": end_min,
                "type": slot_type,
                "is_outage": slot_type == "Definite"
            })
            
            # Тільки відключення (Definite) для основного графіку
            if slot_type != "Definite":
                continue
            
            # Додаємо в графік відключень
            today_schedule.append({
                "start": start_time,
                "end": end_time
            })
            
            # Перевіряємо поточний статус
            if start_min <= current_minutes < end_min:
                # Зараз відключення
                current_outage_end = now.replace(
                    hour=end_hour, 
                    minute=end_minute, 
                    second=0, 
                    microsecond=0
                )
                if end_min > 1440:  # Перехід на наступний день
                    current_outage_end += timedelta(days=1)
                    
            elif current_minutes < start_min:
                # Майбутнє відключення
                future_start = now.replace(
                    hour=start_hour,
                    minute=start_minute,
                    second=0,
                    microsecond=0
                )
                if next_outage_start is None or future_start < next_outage_start:
                    next_outage_start = future_start
        
        # Формуємо текст графіку
        schedule_text = ", ".join([f"{s['start']}-{s['end']}" for s in today_schedule]) if today_schedule else "Немає відключень"
        
        if current_outage_end:
            # Зараз немає світла
            return {
                "status": "Немає світла",
                "next": f"Включать о {current_outage_end.strftime('%H:%M')}",
                "has_power": False,
                "icon": "🔴",
                "schedule": today_schedule,
                "schedule_text": schedule_text,
                "timeline": all_slots_timeline,
                "current_minutes": current_minutes
            }
        elif next_outage_start:
            # Зараз є світло
            delta = next_outage_start - now
            hours = int(delta.total_seconds() // 3600)
            mins = int((delta.total_seconds() % 3600) // 60)
            
            if hours > 0:
                time_str = f"через {hours}г {mins}хв"
            else:
                time_str = f"через {mins}хв"
            
            return {
                "status": "Є світло",
                "next": f"Відключать {time_str}",
                "has_power": True,
                "icon": "🟢",
                "schedule": today_schedule,
                "schedule_text": schedule_text,
                "timeline": all_slots_timeline,
                "current_minutes": current_minutes
            }
        else:
            # Немає відключень на сьогодні
            return {
                "status": "Є світло",
                "next": "Відключень немає",
                "has_power": True,
                "icon": "🟢",
                "schedule": [],
                "schedule_text": "Графіків відключень немає",
                "timeline": all_slots_timeline,
                "current_minutes": current_minutes
            }
            
    except Exception as e:
        print(f"ERROR parse_yasno_new_api: {e}", file=sys.stderr, flush=True)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return None

def parse_yasno_schedule(data, parser_type="yasno_v1"):
    """
    Парсить відповідь від Yasno API та формує компактний статус + графік
    """
    now = datetime.now()
    current_outage_end = None
    next_outage_start = None
    today_schedule = []
    
    try:
        if parser_type == "yasno_v1":
            # Структура Yasno API
            if not isinstance(data, dict):
                print(f"DEBUG: Data is not dict: {type(data)}", file=sys.stderr, flush=True)
                return None
            
            components = data.get("components", [])
            print(f"DEBUG: Found {len(components)} components", file=sys.stderr, flush=True)
            
            for component in components:
                template = component.get("template_name", "")
                print(f"DEBUG: Component template: {template}", file=sys.stderr, flush=True)
                
                if template == "electricity-outages-daily-schedule":
                    schedule = component.get("schedule", {})
                    print(f"DEBUG: Schedule groups: {list(schedule.keys())}", file=sys.stderr, flush=True)
                    
                    # Шукаємо нашу групу
                    group_schedule = schedule.get(POWER_GROUP, [])
                    print(f"DEBUG: Group {POWER_GROUP} has {len(group_schedule)} periods", file=sys.stderr, flush=True)
                    
                    if not group_schedule:
                        # Можливо, група записана інакше, спробуємо всі варіанти
                        for key in schedule.keys():
                            if "3" in key and "2" in key:
                                group_schedule = schedule[key]
                                print(f"DEBUG: Found alternative group key: {key}", file=sys.stderr, flush=True)
                                break
                    
                    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
                    today_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)
                    
                    for period in group_schedule:
                        try:
                            start_str = period.get("start")
                            end_str = period.get("end")
                            
                            if not start_str or not end_str:
                                continue
                            
                            # Парсимо час (підтримка різних форматів)
                            for fmt in ["%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S"]:
                                try:
                                    start_dt = datetime.strptime(start_str.replace('Z', ''), fmt)
                                    end_dt = datetime.strptime(end_str.replace('Z', ''), fmt)
                                    break
                                except:
                                    continue
                            else:
                                # ISO format
                                start_dt = datetime.fromisoformat(start_str.replace('Z', ''))
                                end_dt = datetime.fromisoformat(end_str.replace('Z', ''))
                            
                            # Збираємо графік на сьогодні
                            if today_start <= start_dt <= today_end:
                                today_schedule.append({
                                    "start": start_dt.strftime("%H:%M"),
                                    "end": end_dt.strftime("%H:%M")
                                })
                            
                            # Зараз відключення?
                            if start_dt <= now <= end_dt:
                                current_outage_end = end_dt
                            # Майбутнє відключення?
                            elif now < start_dt:
                                if next_outage_start is None or start_dt < next_outage_start:
                                    next_outage_start = start_dt
                                    
                        except Exception as e:
                            print(f"ERROR parsing period {period}: {e}", file=sys.stderr, flush=True)
                            continue
        
        # Формуємо відповідь
        schedule_text = ", ".join([f"{s['start']}-{s['end']}" for s in today_schedule]) if today_schedule else "Немає відключень"
        
        if current_outage_end:
            # Зараз немає світла
            return {
                "status": "Немає світла",
                "next": f"Включать о {current_outage_end.strftime('%H:%M')}",
                "has_power": False,
                "icon": "🔴",
                "schedule": today_schedule,
                "schedule_text": schedule_text
            }
        elif next_outage_start:
            # Зараз є світло
            delta = next_outage_start - now
            hours = int(delta.total_seconds() // 3600)
            mins = int((delta.total_seconds() % 3600) // 60)
            
            if hours > 0:
                time_str = f"через {hours}г {mins}хв"
            else:
                time_str = f"через {mins}хв"
            
            return {
                "status": "Є світло",
                "next": f"Відключать {time_str}",
                "has_power": True,
                "icon": "🟢",
                "schedule": today_schedule,
                "schedule_text": schedule_text
            }
        else:
            # Немає даних про відключення
            return {
                "status": "Є світло",
                "next": "Графік невідомий",
                "has_power": True,
                "icon": "🟢",
                "schedule": today_schedule,
                "schedule_text": schedule_text if today_schedule else "Дані відсутні"
            }
            
    except Exception as e:
        print(f"ERROR parse_yasno_schedule: {e}", file=sys.stderr, flush=True)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return None

# ===== Столи =====
HALL_TABLES = [1,2,3,4,5,6,8]
TERRACE_TABLES = [7,10,11,12,13]

def fetch_tables_with_waiters():
    target_date = date.today().strftime("%Y%m%d")
    url = (
        f"https://{ACCOUNT_NAME}.joinposter.com/api/dash.getTransactions"
        f"?token={POSTER_TOKEN}&dateFrom={target_date}&dateTo={target_date}"
    )
    try:
        resp = _get(url)
        rows = resp.json().get("response", [])
    except Exception as e:
        print("ERROR tables_with_waiters:", e, file=sys.stderr, flush=True)
        rows = []

    active = {}
    for trx in rows:
        try:
            status = int(trx.get("status", 0))
            if status == 2:
                continue
            tname = int(trx.get("table_name", 0))
            waiter = trx.get("name", "—")
            active[tname] = waiter
        except Exception:
            continue

    def build(zone_numbers):
        out = []
        for tnum in zone_numbers:
            occupied = tnum in active
            waiter = active.get(tnum, "—")
            out.append({
                "id": tnum,
                "name": f"Стол {tnum}",
                "waiter": waiter,
                "occupied": occupied
            })
        return out

    return {"hall": build(HALL_TABLES), "terrace": build(TERRACE_TABLES)}

# ===== Бронювання Choice =====
def fetch_bookings():
    if not CHOICE_TOKEN:
        print("WARNING: CHOICE_TOKEN not set", file=sys.stderr, flush=True)
        return []

    today = date.today()
    from_dt = datetime.combine(today, datetime.min.time())
    till_dt = datetime.combine(today, datetime.max.time())
    
    from_str = from_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    till_str = till_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    
    url = f"https://open-api.choiceqr.com/bookings/list?from={from_str}&till={till_str}&perPage=100"
    
    print(f"DEBUG: Fetching bookings from URL: {url}", file=sys.stderr, flush=True)
    
    headers = {
        "Authorization": f"Bearer {CHOICE_TOKEN}",
        "Content-Type": "application/json"
    }
    
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        
        print(f"DEBUG: Choice API status: {resp.status_code}", file=sys.stderr, flush=True)
        print(f"DEBUG: Choice API response: {resp.text[:500]}", file=sys.stderr, flush=True)
        
        if resp.status_code == 404:
            print("WARNING: Choice API returned 404 - check endpoint URL or restaurant ID", file=sys.stderr, flush=True)
            return []
        
        resp.raise_for_status()
        bookings = resp.json()
        
        if not isinstance(bookings, list):
            print(f"ERROR: Expected list, got {type(bookings)}", file=sys.stderr, flush=True)
            return []
        
        now = datetime.now()
        future_bookings = []
        
        for b in bookings:
            try:
                # Фильтр по статусу - только активные брони
                status = b.get("status", "")
                print(f"DEBUG: Booking status: {status}, time: {b.get('dateTime', 'N/A')}", file=sys.stderr, flush=True)
                
                if status not in ["CREATED", "CONFIRMED", "IN_PROGRESS"]:
                    print(f"DEBUG: Skipping booking with status: {status}", file=sys.stderr, flush=True)
                    continue
                
                dt_str = b.get("dateTime")
                if not dt_str:
                    continue
                
                try:
                    if '+' in dt_str:
                        dt_str_naive = dt_str.split('+')[0]
                    elif 'Z' in dt_str:
                        dt_str_naive = dt_str.replace('Z', '')
                    else:
                        dt_str_naive = dt_str
                    
                    booking_dt = datetime.fromisoformat(dt_str_naive)
                except:
                    booking_dt = datetime.strptime(dt_str[:19], "%Y-%m-%dT%H:%M:%S")
                
                if booking_dt < now:
                    continue
                
                person_count = b.get("personCount", 0)
                customer = b.get("customer", {})
                name = customer.get("name", "—")
                phone = customer.get("phone", "")
                
                future_bookings.append({
                    "time": booking_dt.strftime("%H:%M"),
                    "guests": person_count,
                    "name": name,
                    "phone": phone,
                    "datetime_obj": booking_dt
                })
            except Exception as e:
                print(f"ERROR parsing booking: {e}", file=sys.stderr, flush=True)
                continue
        
        future_bookings.sort(key=lambda x: x["datetime_obj"])
        
        for b in future_bookings:
            del b["datetime_obj"]
        
        print(f"DEBUG: Found {len(future_bookings)} future bookings", file=sys.stderr, flush=True)
        return future_bookings
        
    except Exception as e:
        print(f"ERROR fetching bookings: {e}", file=sys.stderr, flush=True)
        return []

# ===== API =====
@app.route("/api/sales")
def api_sales():
    global CACHE, CACHE_TS
    if time.time() - CACHE_TS > 60:
        sums_today = fetch_category_sales(0)
        sums_prev = fetch_category_sales(7)
        hourly = fetch_transactions_hourly(0)
        prev = fetch_transactions_hourly(7)
        year = fetch_transactions_hourly_year_ago()

        total_hot = sum(sums_today["hot"].values())
        total_cold = sum(sums_today["cold"].values())
        total_bar = sum(sums_today["bar"].values())
        total_sum = total_hot + total_cold + total_bar
        share = {
            "hot": round(total_hot/total_sum*100) if total_sum else 0,
            "cold": round(total_cold/total_sum*100) if total_sum else 0,
            "bar": round(total_bar/total_sum*100) if total_sum else 0,
        }

        CACHE.update({
            "hot": sums_today["hot"], "cold": sums_today["cold"],
            "hot_prev": sums_prev["hot"], "cold_prev": sums_prev["cold"],
            "hourly": hourly, "hourly_prev": prev, "hourly_year": year,
            "share": share, "weather": fetch_weather()
        })
        CACHE_TS = time.time()

    return jsonify(CACHE)

@app.route("/api/tables")
def api_tables():
    return jsonify(fetch_tables_with_waiters())

@app.route("/api/bookings")
def api_bookings():
    global BOOKINGS_CACHE, BOOKINGS_CACHE_TS
    if time.time() - BOOKINGS_CACHE_TS > 600:
        BOOKINGS_CACHE = fetch_bookings()
        BOOKINGS_CACHE_TS = time.time()
    return jsonify(BOOKINGS_CACHE)

@app.route("/api/power")
def api_power():
    return jsonify(fetch_power_status())

@app.route("/api/power/debug")
def api_power_debug():
    """Debug endpoint для перевірки сирих даних від Yasno API"""
    try:
        url = "https://api.yasno.com.ua/api/v1/pages/home/schedule-turn-off-electricity"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
            "Accept-Language": "uk-UA,uk;q=0.9"
        }
        resp = requests.get(url, headers=headers, timeout=15)
        return jsonify({
            "status_code": resp.status_code,
            "data": resp.json() if resp.status_code == 200 else None,
            "error": None
        })
    except Exception as e:
        return jsonify({
            "status_code": None,
            "data": None,
            "error": str(e)
        })


# ===== UI =====
@app.route("/")
def index():
    template = """
    <!DOCTYPE html>
    <html lang="uk">
    <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Kitchen Dashboard</title>
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-datalabels@2"></script>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
        <style>
            * {
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }

            :root {
                --bg-primary: #000000;
                --bg-secondary: #1c1c1e;
                --bg-tertiary: #2c2c2e;
                --text-primary: #ffffff;
                --text-secondary: #8e8e93;
                --accent-hot: #ff9500;
                --accent-cold: #007aff;
                --accent-bar: #af52de;
                --accent-booking: #34c759;
                --accent-success: #30d158;
                --accent-warning: #ff9500;
                --accent-danger: #ff453a;
                --border-color: #38383a;
                --shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
            }

            body {
                font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                background: var(--bg-primary);
                color: var(--text-primary);
                overflow: hidden;
                height: 100vh;
                padding: 8px;
            }

            .dashboard {
                display: grid;
                grid-template-columns: 1fr 1fr 1fr 1fr 1fr;
                grid-template-rows: minmax(0, 32vh) minmax(0, 60vh);
                gap: 8px;
                height: calc(100vh - 16px);
                max-height: calc(100vh - 16px);
                padding: 0;
            }

            .card {
                background: var(--bg-secondary);
                border-radius: 12px;
                padding: 10px;
                border: 1px solid var(--border-color);
                box-shadow: var(--shadow);
                overflow: hidden;
                display: flex;
                flex-direction: column;
                min-height: 0;
            }

            .card h2 {
                font-size: 13px;
                font-weight: 600;
                margin-bottom: 8px;
                display: flex;
                align-items: center;
                gap: 6px;
                color: var(--text-primary);
            }

            .card.hot h2 { color: var(--accent-hot); }
            .card.cold h2 { color: var(--accent-cold); }
            .card.share h2 { color: var(--accent-bar); }
            .card.bookings h2 { color: var(--accent-booking); }

            .card.top-card { min-height: 0; }

            table {
                width: 100%;
                border-collapse: collapse;
                font-size: 12px;
            }

            th, td {
                padding: 4px 6px;
                text-align: right;
                border-bottom: 1px solid var(--border-color);
            }

            th:first-child, td:first-child { text-align: left; }

            th {
                color: var(--text-secondary);
                font-weight: 600;
                font-size: 10px;
                text-transform: uppercase;
                letter-spacing: 0.5px;
            }

            td { color: var(--text-primary); font-weight: 600; font-size: 12px; }

            .pie-container {
                flex: 1;
                display: flex;
                align-items: center;
                justify-content: center;
                min-height: 0;
                position: relative;
                padding: 5px;
            }

            .time-weather {
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
                text-align: center;
                flex: 1;
                padding: 0px;
                height: 100%;
                min-height: 0;
            }

            .clock {
                font-size: 56px;
                font-weight: 900;
                color: var(--text-primary);
                font-variant-numeric: tabular-nums;
                margin-bottom: 4px;
                line-height: 0.9;
            }

            .weather {
                display: flex;
                flex-direction: column;
                align-items: center;
                gap: 2px;
                flex: 1;
            }

            .weather img { width: 80px; height: 80px; margin: 0; }
            .temp { font-size: 30px; font-weight: 800; color: var(--text-primary); line-height: 1; }
            .desc { font-size: 13px; color: var(--text-secondary); text-align: center; font-weight: 600; }

            .power-status {
                margin-top: 8px;
                padding: 8px 12px;
                background: var(--bg-tertiary);
                border-radius: 8px;
                border: 1px solid var(--border-color);
                display: flex;
                align-items: center;
                gap: 8px;
                font-size: 11px;
                transition: all 0.3s ease;
            }

            .power-status .icon {
                font-size: 16px;
                line-height: 1;
            }

            .power-status .text {
                flex: 1;
                text-align: left;
            }

            .power-status .status {
                font-weight: 700;
                color: var(--text-primary);
            }

            .power-status .next {
                font-weight: 500;
                color: var(--text-secondary);
                font-size: 10px;
            }

            .power-status.has-power {
                background: linear-gradient(135deg, rgba(52, 199, 89, 0.1), rgba(48, 209, 88, 0.05));
                border-color: rgba(52, 199, 89, 0.3);
            }

            .power-status.no-power {
                background: linear-gradient(135deg, rgba(255, 59, 48, 0.1), rgba(255, 69, 58, 0.05));
                border-color: rgba(255, 59, 48, 0.3);
            }

            .power-schedule {
                font-size: 9px;
                color: var(--text-secondary);
                margin-top: 2px;
                font-weight: 500;
                line-height: 1.3;
            }
            
            .power-timeline {
                margin-top: 8px;
                padding: 8px;
                background: var(--bg-tertiary);
                border-radius: 6px;
            }
            
            .timeline-header {
                display: flex;
                justify-content: space-between;
                font-size: 8px;
                color: var(--text-secondary);
                margin-bottom: 4px;
                font-weight: 600;
            }
            
            .timeline-bar {
                height: 20px;
                background: linear-gradient(90deg, rgba(52, 199, 89, 0.2) 0%, rgba(52, 199, 89, 0.2) 100%);
                border-radius: 4px;
                position: relative;
                overflow: hidden;
                border: 1px solid rgba(52, 199, 89, 0.3);
            }
            
            .timeline-segment {
                position: absolute;
                height: 100%;
                top: 0;
                transition: all 0.3s ease;
            }
            
            .timeline-segment.outage {
                background: linear-gradient(90deg, rgba(255, 59, 48, 0.8), rgba(255, 69, 58, 0.6));
                border-right: 1px solid rgba(255, 59, 48, 0.5);
            }
            
            .timeline-segment.has-power {
                background: linear-gradient(90deg, rgba(52, 199, 89, 0.6), rgba(52, 199, 89, 0.4));
            }
            
            .timeline-current {
                position: absolute;
                top: -2px;
                bottom: -2px;
                width: 2px;
                background: #ffffff;
                z-index: 10;
                box-shadow: 0 0 8px rgba(255, 255, 255, 0.8);
            }
            
            .timeline-labels {
                display: flex;
                justify-content: space-between;
                margin-top: 4px;
                font-size: 7px;
                color: var(--text-secondary);
                font-weight: 600;
            }


            .chart-card {
                grid-column: 1 / 4;
                display: flex;
                flex-direction: column;
                min-height: 0;
            }

            .chart-container {
                flex: 1;
                min-height: 0;
                position: relative;
            }

            .bookings-card {
                grid-column: 4 / 5;
                display: flex;
                flex-direction: column;
                min-height: 0;
            }

            .bookings-list {
                flex: 1;
                overflow-y: auto;
                overflow-x: hidden;
                min-height: 0;
                padding-right: 2px;
            }

            .bookings-list::-webkit-scrollbar {
                width: 5px;
            }

            .bookings-list::-webkit-scrollbar-track {
                background: var(--bg-tertiary);
                border-radius: 3px;
            }

            .bookings-list::-webkit-scrollbar-thumb {
                background: var(--border-color);
                border-radius: 3px;
            }

            .bookings-list::-webkit-scrollbar-thumb:hover {
                background: var(--text-secondary);
            }

            .booking-item {
                background: var(--bg-tertiary);
                border-radius: 6px;
                padding: 6px 8px;
                margin-bottom: 4px;
                border: 1px solid var(--border-color);
                transition: all 0.2s ease;
            }

            .booking-item:hover {
                border-color: var(--accent-booking);
                background: rgba(52, 199, 89, 0.1);
            }

            .booking-time {
                font-size: 16px;
                font-weight: 800;
                color: var(--accent-booking);
                margin-bottom: 1px;
            }

            .booking-guests {
                font-size: 12px;
                font-weight: 700;
                color: var(--text-primary);
                display: flex;
                align-items: center;
                gap: 4px;
            }

            .booking-empty {
                text-align: center;
                padding: 30px 15px;
                color: var(--text-secondary);
                font-size: 13px;
            }

            .tables-card {
                grid-column: 5 / 6;
                grid-row: 1 / 3;
                display: flex;
                flex-direction: column;
                min-height: 0;
            }

            .tables-content {
                flex: 1;
                display: flex;
                flex-direction: column;
                gap: 8px;
                min-height: 0;
                overflow: hidden;
            }

            .tables-zone {
                min-height: 0;
                display: flex;
                flex-direction: column;
            }

            .tables-zone:first-child {
                flex: 1.4;
            }

            .tables-zone:last-child {
                flex: 1;
            }

            .tables-zone h3 {
                font-size: 11px;
                font-weight: 600;
                margin-bottom: 5px;
                color: var(--text-secondary);
                display: flex;
                align-items: center;
                gap: 4px;
            }

            .tables-grid {
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 5px;
                flex: 1;
                align-content: start;
            }

            .tables-zone:first-child .tables-grid {
                grid-auto-rows: 90px;
            }

            .tables-zone:last-child .tables-grid {
                grid-auto-rows: 70px;
            }

            .table-tile {
                border-radius: 10px;
                padding: 8px 6px;
                font-weight: 700;
                text-align: center;
                font-size: 14px;
                display: flex;
                flex-direction: column;
                justify-content: center;
                gap: 4px;
                transition: all 0.2s ease;
                border: 1px solid var(--border-color);
                background: var(--bg-tertiary);
                width: 100%;
                height: 100%;
                color: var(--text-secondary);
            }

            .table-tile.occupied {
                background: linear-gradient(135deg, var(--accent-cold), #005ecb);
                color: white;
                border-color: var(--accent-cold);
                box-shadow: 0 2px 8px rgba(0, 122, 255, 0.3);
            }

            .tables-zone:first-child .table-number { 
                font-weight: 800; 
                font-size: 16px; 
                margin-bottom: 2px; 
            }

            .tables-zone:last-child .table-number { 
                font-weight: 800; 
                font-size: 13px; 
                margin-bottom: 1px; 
            }

            .tables-zone:first-child .table-waiter { 
                font-size: 12px; 
                font-weight: 700; 
                opacity: 0.95; 
                overflow: hidden; 
                text-overflow: ellipsis; 
                white-space: nowrap; 
                max-width: 100%; 
                line-height: 1.2; 
            }

            .tables-zone:last-child .table-waiter { 
                font-size: 10px; 
                font-weight: 700; 
                opacity: 0.95; 
                overflow: hidden; 
                text-overflow: ellipsis; 
                white-space: nowrap; 
                max-width: 100%; 
                line-height: 1.1; 
            }

            .logo {
                position: fixed;
                right: 15px;
                bottom: 5px;
                font-family: 'Inter', sans-serif;
                font-weight: 800;
                font-size: 13px;
                color: #ffffff;
                z-index: 1000;
                background: var(--bg-secondary);
                padding: 3px 7px;
                border-radius: 6px;
                border: 1px solid var(--border-color);
            }

            canvas { max-width: 100% !important; max-height: 100% !important; }
        </style>
    </head>
    <body>
        <div class="dashboard">
            <div class="card hot top-card">
                <h2>🔥 Гарячий цех</h2>
                <div style="flex: 1; overflow: hidden;">
                    <table id="hot_tbl"></table>
                </div>
            </div>

            <div class="card cold top-card">
                <h2>❄️ Холодний цех</h2>
                <div style="flex: 1; overflow: hidden;">
                    <table id="cold_tbl"></table>
                </div>
            </div>

            <div class="card share top-card">
                <h2>📊 Розподіл замовлень</h2>
                <div class="pie-container">
                    <canvas id="pie" width="160" height="160"></canvas>
                </div>
            </div>

            <div class="card top-card" style="grid-column: 4 / 5;">
                <h2>🕐 Час і погода</h2>
                <div class="time-weather">
                    <div id="clock" class="clock"></div>
                    <div class="weather">
                        <div id="weather-icon"></div>
                        <div id="weather-temp" class="temp"></div>
                        <div id="weather-desc" class="desc"></div>
                    </div>
                    <div id="power-status" class="power-status">
                        <span class="icon">❓</span>
                        <div class="text">
                            <div class="status">Завантаження...</div>
                            <div class="next"></div>
                            <div class="power-schedule"></div>
                        </div>
                    </div>
                    <div id="power-timeline" class="power-timeline" style="display: none;">
                        <div class="timeline-header">
                            <span>00:00</span>
                            <span>График відключень на сьогодні</span>
                            <span>24:00</span>
                        </div>
                        <div class="timeline-bar" id="timeline-bar"></div>
                        <div class="timeline-labels">
                            <span>0</span>
                            <span>6</span>
                            <span>12</span>
                            <span>18</span>
                            <span>24</span>
                        </div>
                    </div>
                </div>
            </div>

            <div class="card chart-card">
                <h2>📈 Замовлення по годинам (накопич.)</h2>
                <div class="chart-container">
                    <canvas id="chart"></canvas>
                </div>
            </div>

            <div class="card bookings-card bookings">
                <h2>📅 Бронювання</h2>
                <div id="bookings-list" class="bookings-list"></div>
            </div>

            <div class="card tables-card">
                <h2>🍽️ Столи</h2>
                <div class="tables-content">
                    <div class="tables-zone">
                        <h3>🛋️ Зал</h3>
                        <div id="hall" class="tables-grid"></div>
                    </div>
                    <div class="tables-zone">
                        <h3>🌿 Літня тераса</h3>
                        <div id="terrace" class="tables-grid"></div>
                    </div>
                </div>
            </div>
        </div>

        <div class="logo">GRECO Tech ™</div>

        <script>
        let chart, pie;

        function cutToNow(labels, arr){
            const now = new Date();
            const curHour = now.getHours();
            let cutIndex = labels.findIndex(l => parseInt(l) > curHour);
            if(cutIndex === -1) cutIndex = labels.length;
            return arr.slice(0, cutIndex);
        }

        function renderTables(zoneId, data){
            const el = document.getElementById(zoneId);
            el.innerHTML = "";
            data.forEach(t=>{
                const div = document.createElement("div");
                div.className = "table-tile " + (t.occupied ? "occupied":"");
                div.innerHTML = `
                    <div class="table-number">${t.name}</div>
                    <div class="table-waiter">${t.waiter}</div>
                `;
                el.appendChild(div);
            });
        }

        function renderBookings(bookings){
            const el = document.getElementById('bookings-list');
            
            if(!bookings || bookings.length === 0){
                el.innerHTML = '<div class="booking-empty">🎉 Поки немає бронювань</div>';
                return;
            }

            // Фільтруємо тільки майбутні бронювання
            const now = new Date();
            const currentTime = now.getHours() * 60 + now.getMinutes();
            
            const futureBookings = bookings.filter(b => {
                const [hours, minutes] = b.time.split(':').map(Number);
                const bookingTime = hours * 60 + minutes;
                return bookingTime > currentTime;
            });

            if(futureBookings.length === 0){
                el.innerHTML = '<div class="booking-empty">🎉 Поки немає бронювань</div>';
                return;
            }

            el.innerHTML = '';
            futureBookings.forEach(b => {
                const div = document.createElement('div');
                div.className = 'booking-item';
                div.innerHTML = `
                    <div class="booking-time">${b.time}</div>
                    <div class="booking-guests">👥 ${b.guests} ${b.guests === 1 ? 'гість' : 'гостей'}</div>
                `;
                el.appendChild(div);
            });
        }

        async function refresh(){
            const r = await fetch('/api/sales');
            const data = await r.json();

            function fill(id, today, prev){
                const el = document.getElementById(id);
                let html = "<tr><th>Категорія</th><th>Сьогодні</th><th>Мин. тиждень</th></tr>";
                const keys = new Set([...Object.keys(today || {}), ...Object.keys(prev || {})]);
                [...keys].sort().forEach(k => {
                    html += `<tr><td>${k}</td><td>${(today||{})[k]||0}</td><td>${(prev||{})[k]||0}</td></tr>`;
                });
                el.innerHTML = html;
            }
            fill('hot_tbl', data.hot||{}, data.hot_prev||{});
            fill('cold_tbl', data.cold||{}, data.cold_prev||{});

            Chart.register(ChartDataLabels);
            const ctx2 = document.getElementById('pie').getContext('2d');
            if(pie) pie.destroy();
            pie = new Chart(ctx2,{
                type:'pie',
                data:{
                    labels:['Гар.цех','Хол.цех','Бар'],
                    datasets:[{
                        data:[data.share.hot,data.share.cold,data.share.bar],
                        backgroundColor:['#ff9500','#007aff','#af52de'],
                        borderWidth: 2,
                        borderColor: '#000'
                    }]
                },
                options:{
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins:{
                        legend:{display:false},
                        tooltip:{enabled:false},
                        datalabels:{
                            color:'#fff',
                            font:{weight:'bold', size:10, family:'Inter'},
                            formatter:function(value, context){
                                const label = context.chart.data.labels[context.dataIndex];
                                return label + '\\n' + value + '%';
                            },
                            textAlign: 'center'
                        }
                    }
                }
            });

            let today_hot = cutToNow(data.hourly.labels, data.hourly.hot);
            let today_cold = cutToNow(data.hourly.labels, data.hourly.cold);

            const ctx = document.getElementById('chart').getContext('2d');
            if(chart) chart.destroy();
            chart = new Chart(ctx,{
                type:'line',
                data:{
                    labels:data.hourly.labels,
                    datasets:[
                        {
                            label:'Сьогодні (Гарячий)',
                            data:today_hot,
                            borderColor:'#ff9500',
                            backgroundColor:'rgba(255, 149, 0, 0.1)',
                            tension:0.4,
                            fill:false,
                            borderWidth: 3,
                            pointRadius: 4,
                            pointBackgroundColor: '#ff9500'
                        },
                        {
                            label:'Сьогодні (Холодний)',
                            data:today_cold,
                            borderColor:'#007aff',
                            backgroundColor:'rgba(0, 122, 255, 0.1)',
                            tension:0.4,
                            fill:false,
                            borderWidth: 3,
                            pointRadius: 4,
                            pointBackgroundColor: '#007aff'
                        },
                        {
                            label:'Прошла неділя (Гарячий)',
                            data:data.hourly_prev.hot,
                            borderColor:'rgba(255, 149, 0, 0.7)',
                            borderDash:[8,5],
                            tension:0.4,
                            fill:false,
                            borderWidth: 2,
                            pointRadius: 0
                        },
                        {
                            label:'Прошла неділя (Холодний)',
                            data:data.hourly_prev.cold,
                            borderColor:'rgba(0, 122, 255, 0.7)',
                            borderDash:[8,5],
                            tension:0.4,
                            fill:false,
                            borderWidth: 2,
                            pointRadius: 0
                        },
                        {
                            label:'Прошлий рік (Гарячий)',
                            data:data.hourly_year.hot,
                            borderColor:'rgba(255, 149, 0, 0.35)',
                            tension:0.4,
                            fill:false,
                            borderWidth: 1.5,
                            pointRadius: 0
                        },
                        {
                            label:'Прошлий рік (Холодний)',
                            data:data.hourly_year.cold,
                            borderColor:'rgba(0, 122, 255, 0.35)',
                            tension:0.4,
                            fill:false,
                            borderWidth: 1.5,
                            pointRadius: 0
                        }
                    ]
                },
                options:{
                    responsive:true,
                    maintainAspectRatio: false,
                    interaction: { intersect: false, mode: 'index' },
                    plugins:{
                        legend:{
                            display: true,
                            labels:{
                                color: '#ffffff',
                                font: { 
                                    size: 11, 
                                    weight: '600',
                                    family: 'Inter'
                                },
                                usePointStyle: true,
                                padding: 10,
                                boxWidth: 10,
                                boxHeight: 10,
                                generateLabels: function(chart) {
                                    const datasets = chart.data.datasets;
                                    return datasets.map((dataset, i) => {
                                        let pointStyle = 'circle';
                                        
                                        if (i === 2 || i === 3) {
                                            pointStyle = 'line';
                                        }
                                        else if (i === 4 || i === 5) {
                                            pointStyle = 'rect';
                                        }
                                        
                                        return {
                                            text: dataset.label,
                                            fillStyle: dataset.borderColor,
                                            strokeStyle: dataset.borderColor,
                                            lineWidth: 2,
                                            hidden: !chart.isDatasetVisible(i),
                                            index: i,
                                            pointStyle: pointStyle,
                                            fontColor: '#ffffff'
                                        };
                                    });
                                }
                            }
                        },
                        datalabels:{display:false}
                    },
                    scales:{
                        x:{
                            ticks:{color:'#ffffff', font: { size: 10 }},
                            grid:{color:'rgba(142, 142, 147, 0.2)'},
                            border:{color:'#38383a'}
                        },
                        y:{
                            ticks:{color:'#ffffff', font: { size: 10 }},
                            grid:{color:'rgba(142, 142, 147, 0.2)'},
                            border:{color:'#38383a'},
                            beginAtZero:true
                        }
                    }
                }
            });

            const now = new Date();
            document.getElementById('clock').innerText = now.toLocaleTimeString('uk-UA',{hour:'2-digit',minute:'2-digit'});
            
            const w = data.weather||{};
            const iconEl = document.getElementById('weather-icon');
            const tempEl = document.getElementById('weather-temp');
            const descEl = document.getElementById('weather-desc');
            
            if(w.icon) {
                iconEl.innerHTML = `<img src="https://openweathermap.org/img/wn/${w.icon}@2x.png" alt="weather">`;
            } else {
                iconEl.innerHTML = '';
            }
            
            tempEl.textContent = w.temp || '—';
            descEl.textContent = w.desc || '—';
        }

        async function refreshPower(){
            try {
                const r = await fetch('/api/power');
                const data = await r.json();
                
                const statusEl = document.getElementById('power-status');
                const iconEl = statusEl.querySelector('.icon');
                const statusText = statusEl.querySelector('.status');
                const nextText = statusEl.querySelector('.next');
                const scheduleText = statusEl.querySelector('.power-schedule');
                
                // Оновлюємо іконку
                iconEl.textContent = data.icon || '❓';
                
                // Оновлюємо текст
                statusText.textContent = data.status || 'Н/Д';
                nextText.textContent = data.next || '';
                
                // Оновлюємо графік на сьогодні
                if (data.schedule_text) {
                    scheduleText.textContent = '📅 Сьогодні: ' + data.schedule_text;
                } else {
                    scheduleText.textContent = '';
                }
                
                // Оновлюємо стилі
                statusEl.classList.remove('has-power', 'no-power');
                if (data.has_power === true) {
                    statusEl.classList.add('has-power');
                } else if (data.has_power === false) {
                    statusEl.classList.add('no-power');
                }
                
                // Візуальний таймлайн
                const timelineContainer = document.getElementById('power-timeline');
                const timelineBar = document.getElementById('timeline-bar');
                
                if (data.timeline && data.timeline.length > 0) {
                    timelineContainer.style.display = 'block';
                    timelineBar.innerHTML = '';
                    
                    // Відображаємо всі сегменти
                    data.timeline.forEach(slot => {
                        const segment = document.createElement('div');
                        segment.className = 'timeline-segment';
                        
                        // Позиція та ширина в процентах від 24 годин (1440 хвилин)
                        const leftPercent = (slot.start_min / 1440) * 100;
                        const widthPercent = ((slot.end_min - slot.start_min) / 1440) * 100;
                        
                        segment.style.left = leftPercent + '%';
                        segment.style.width = widthPercent + '%';
                        
                        if (slot.is_outage) {
                            segment.classList.add('outage');
                            segment.title = `Відключення: ${slot.start} - ${slot.end}`;
                        } else {
                            segment.classList.add('has-power');
                            segment.title = `Світло: ${slot.start} - ${slot.end}`;
                        }
                        
                        timelineBar.appendChild(segment);
                    });
                    
                    // Додаємо індикатор поточного часу
                    if (data.current_minutes !== undefined) {
                        const currentMarker = document.createElement('div');
                        currentMarker.className = 'timeline-current';
                        const currentPercent = (data.current_minutes / 1440) * 100;
                        currentMarker.style.left = currentPercent + '%';
                        currentMarker.title = 'Зараз';
                        timelineBar.appendChild(currentMarker);
                    }
                } else {
                    timelineContainer.style.display = 'none';
                }
            } catch (e) {
                console.error('Power status error:', e);
            }
        }

        async function refreshTables(){
            const r = await fetch('/api/tables');
            const data = await r.json();
            renderTables('hall', data.hall||[]);
            renderTables('terrace', data.terrace||[]);
        }

        async function refreshBookings(){
            const r = await fetch('/api/bookings');
            const bookings = await r.json();
            renderBookings(bookings);
        }

        refresh(); 
        refreshTables();
        refreshBookings();
        refreshPower();

        setInterval(refresh, 60000);
        setInterval(refreshTables, 30000);
        setInterval(refreshBookings, 600000);
        setInterval(refreshPower, 300000); // Кожні 5 хвилин
        </script>
    </body>
    </html>
    """
    return render_template_string(template)

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
