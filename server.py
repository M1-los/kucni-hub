import http.server
import socketserver
import sqlite3
import json
import os
import re
import sys
import threading
import time
import urllib.request
import urllib.parse
from datetime import datetime

PORT = int(os.environ.get("PORT", 8000))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "kucnihub.db")
PUBLIC_DIR = os.path.join(BASE_DIR, "public")
TUNNEL_LOG = os.path.join(BASE_DIR, "tunnel.log")

DAYS_SR = ["Ponedeljak", "Utorak", "Sreda", "Četvrtak", "Petak", "Subota", "Nedelja"]

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def get_public_url():
    return "https://kucni-hub.onrender.com"


def is_in_quiet_hours(now):
    # From 22:00 (10 PM) until 08:30 AM (stores closed)
    h = now.hour
    m = now.minute
    if h >= 22 or h < 8 or (h == 8 and m < 30):
        return True
    return False

def init_db():
    conn = get_db()
    c = conn.cursor()

    c.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            avatar TEXT,
            color TEXT
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            zone TEXT NOT NULL,
            recurrence TEXT NOT NULL,
            icon TEXT,
            frequency_days INTEGER DEFAULT 1,
            last_completed_at TEXT,
            completed_by TEXT,
            is_completed_today INTEGER DEFAULT 0,
            room_day TEXT
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS shopping_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            category TEXT NOT NULL,
            quantity TEXT DEFAULT '1',
            added_by TEXT DEFAULT 'Miloš',
            is_bought INTEGER DEFAULT 0,
            bought_by TEXT,
            created_at TEXT,
            bought_at TEXT,
            is_urgent INTEGER DEFAULT 0,
            last_notified_at TEXT
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL,
            user_name TEXT NOT NULL,
            type TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    ''')

    conn.commit()

    default_settings = {
        'telegram_bot_token': '',
        'telegram_chat_id': '',
        'telegram_user_name': '',
        'telegram_connected_at': '',
        'reminder_time': '09:00',
        'last_reminder_date': '',
        'last_urgent_notify': '0',
        'last_regular_notify': '0',
        'notifications_enabled': '1',
        'quiet_hours_enabled': '1',
        'active_user': 'milos'
    }
    for k, v in default_settings.items():
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))
    conn.commit()
    conn.close()

def log_activity(text, user_name, act_type="general"):
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute(
            "INSERT INTO activity_log (text, user_name, type, created_at) VALUES (?, ?, ?, ?)",
            (text, user_name, act_type, datetime.now().strftime("%d.%m. %H:%M"))
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[Error logging]: {e}")

def send_telegram_message(text, target_chat_id=None, parse_mode="HTML"):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key='telegram_bot_token'")
    token_row = c.fetchone()
    c.execute("SELECT value FROM settings WHERE key='telegram_chat_id'")
    chat_row = c.fetchone()
    conn.close()

    token = (token_row[0] if token_row else "").strip()
    chat_id = target_chat_id or (chat_row[0] if chat_row else "").strip()

    if not token or not chat_id:
        return False, "Bot token ili Chat ID nisu podešeni."

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode
    }

    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=8) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            return True, res_data
    except Exception as e:
        print(f"[Telegram error]: {e}")
        return False, str(e)

# Telegram Bot Poller
def telegram_polling_worker():
    last_update_id = 0
    print("[Telegram] Poller pokrenut (sa podrškom za prirodan govor).")

    while True:
        try:
            conn = get_db()
            c = conn.cursor()
            c.execute("SELECT value FROM settings WHERE key='telegram_bot_token'")
            token_row = c.fetchone()
            conn.close()

            token = (token_row[0] if token_row else "").strip()
            if not token:
                time.sleep(3)
                continue

            url = f"https://api.telegram.org/bot{token}/getUpdates?offset={last_update_id + 1}&timeout=15"
            req = urllib.request.Request(url, headers={"User-Agent": "KucniHub/7.0"})
            with urllib.request.urlopen(req, timeout=20) as response:
                result = json.loads(response.read().decode("utf-8"))
                if result.get("ok"):
                    for update in result.get("result", []):
                        last_update_id = update["update_id"]
                        handle_telegram_update(update, token)
        except Exception as e:
            time.sleep(3)

def handle_telegram_update(update, token):
    message = update.get("message")
    if not message:
        return

    chat_id = str(message.get("chat", {}).get("id"))
    raw_text = (message.get("text") or "").strip()
    from_user = message.get("from", {})
    sender_name = from_user.get("first_name", "Miloš")
    username = from_user.get("username", "")

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT value FROM settings WHERE key='telegram_chat_id'")
    curr_chat = c.fetchone()[0]
    
    if not curr_chat or curr_chat != chat_id:
        c.execute("UPDATE settings SET value=? WHERE key='telegram_chat_id'", (chat_id,))
        c.execute("UPDATE settings SET value=? WHERE key='telegram_user_name'", (f"{sender_name} (@{username})" if username else sender_name,))
        c.execute("UPDATE settings SET value=? WHERE key='telegram_connected_at'", (datetime.now().strftime("%d.%m.%Y %H:%M"),))
        conn.commit()
        log_activity(f"Povezan Telegram: {sender_name}", sender_name, "telegram_connected")
    conn.close()

    if not raw_text:
        return

    # Process message naturally or via slash commands
    process_conversational_message(raw_text, sender_name, chat_id)

# NATURAL LANGUAGE CONVERSATIONAL PROCESSOR (Prirodan govor bez kucanja "/")
def process_conversational_message(text, sender_name, chat_id):
    clean = text.strip()
    lower = clean.lower()

    # Remove accents for easier keyword matching
    normalized = lower.replace('ć', 'c').replace('č', 'c').replace('š', 's').replace('ž', 'z').replace('đ', 'dj')

    # 1. GREETINGS & SMALL TALK
    if normalized in ['cao', 'zdravo', 'hej', 'dobro jutro', 'dobar dan', 'dobro vece', 'start', '/start']:
        pub_url = get_public_url()
        reply = (
            f"👋 <b>Ćao {sender_name}!</b> Tu sam.\n\n"
            f"Možeš mi pisati <b>potpuno prirodno</b>:\n"
            f"• <i>„kupi mleko i hleb”</i> — dodaje na spisak\n"
            f"• <i>„hitno nam treba omekšivač”</i> — alarm na 30 min\n"
            f"• <i>„kupio sam mleko”</i> — briše sa spiska\n"
            f"• <i>„sredio sam kupatilo”</i> / <i>„oprao sudove”</i> — beleži zadatke\n\n"
            f"📋 <b>Glavne komande i prečice:</b>\n"
            f"• <b>„status”</b> ili <b>„kako stojimo”</b> — stanje poslova i kupovine\n"
            f"• <b>„šta treba da se kupi”</b> — ceo aktivni spisak\n"
            f"• <b>„proveri”</b> — kućni inventar i provera frižidera\n"
            f"• <b>„pauziraj”</b> / <b>„nastavi”</b> — gašenje/paljenje notifikacija\n\n"
            f"🔗 <b>Tvoj Dashboard:</b> {pub_url}"
        )
        send_telegram_message(reply, target_chat_id=chat_id)
        return

    if normalized in ['hvala', 'hvala ti', 'fala', 'hvala lepo', 'super', 'top', 'ekstra', 'bravo', 'svaka cast']:
        send_telegram_message(f"Nema na čemu {sender_name}! Tu sam za sve oko stana i nabavke. 🏠✨", target_chat_id=chat_id)
        return

    # 2. PAUSE / RESUME NOTIFICATIONS (Prirodan govor)
    if any(phrase in normalized for phrase in ['pauziraj', 'ugasi notifikacije', 'iskljuci notifikacije', 'nemoj da saljes', 'utisaj se', '/pauza', '/mute']):
        conn = get_db()
        c = conn.cursor()
        c.execute("UPDATE settings SET value='0' WHERE key='notifications_enabled'")
        conn.commit()
        conn.close()
        log_activity(f"Pauzirao/la notifikacije", sender_name, "notif_paused")
        send_telegram_message("🔕 <b>Notifikacije su pauzirane!</b> Neću ti slati podsetnike dok ne napišeš <i>„nastavi”</i> ili ih uključiš na sajtu.", target_chat_id=chat_id)
        return

    if any(phrase in normalized for phrase in ['nastavi', 'ukljuci notifikacije', 'aktiviraj notifikacije', 'upali notifikacije', '/nastavi', '/unmute']):
        conn = get_db()
        c = conn.cursor()
        c.execute("UPDATE settings SET value='1' WHERE key='notifications_enabled'")
        conn.commit()
        conn.close()
        log_activity(f"Aktivirao/la notifikacije", sender_name, "notif_resumed")
        send_telegram_message("🔔 <b>Notifikacije su ponovo aktivne!</b>\n<i>(Standardne idu na svaka 2h, hitne na 30 min, sa noćnim mirom posle 22:00).</i>", target_chat_id=chat_id)
        return

    # 3. MARK BOUGHT ("kupio sam...", "uzeo sam...", "kupljeno...", "kupio sve")
    bought_match = re.search(r'\b(kupio|kupila|uzeo|uzela|kupljeno|resio|nabavio)\b(?:\s+sam)?\s+(.+)', normalized)
    if bought_match or normalized.startswith('/kupio') or normalized.startswith('/kupljeno'):
        query_val = bought_match.group(2).strip() if bought_match else clean.split(' ', 1)[-1].strip()

        if query_val.lower() in ["sve", "all", "sve sa spiska"]:
            conn = get_db()
            c = conn.cursor()
            c.execute("UPDATE shopping_items SET is_bought=1, bought_by=?, bought_at=? WHERE is_bought=0", (sender_name, datetime.now().strftime("%d.%m. %H:%M")))
            conn.commit()
            conn.close()
            send_telegram_message("🎉 <b>Sve stavke sa spiska su označene kao kupljene!</b> Svi podsetnici su ugašeni. Svaka čast!", target_chat_id=chat_id)
            return

        # Support multiple items: e.g. "mleko i hleb" or comma separated
        items_to_match = re.split(r'\s+i\s+|,\s*', query_val)
        conn = get_db()
        c = conn.cursor()
        marked = []

        for itm in items_to_match:
            itm = itm.strip().lower()
            if not itm:
                continue
            if itm.isdigit():
                idx = int(itm)
                c.execute("SELECT id, title FROM shopping_items WHERE is_bought=0 ORDER BY is_urgent DESC, id DESC")
                rows = c.fetchall()
                if 1 <= idx <= len(rows):
                    t = rows[idx - 1]
                    c.execute("UPDATE shopping_items SET is_bought=1, bought_by=?, bought_at=? WHERE id=?", (sender_name, datetime.now().strftime("%d.%m. %H:%M"), t["id"]))
                    marked.append(t["title"])
            else:
                c.execute("SELECT id, title FROM shopping_items WHERE is_bought=0 AND (LOWER(title) LIKE ? OR LOWER(title) LIKE ?) LIMIT 1", (f"%{itm}%", f"{itm}%"))
                row = c.fetchone()
                if row:
                    c.execute("UPDATE shopping_items SET is_bought=1, bought_by=?, bought_at=? WHERE id=?", (sender_name, datetime.now().strftime("%d.%m. %H:%M"), row["id"]))
                    marked.append(row["title"])

        conn.commit()
        conn.close()

        if marked:
            joined_titles = ", ".join(marked)
            log_activity(f"Kupio/la: '{joined_titles}'", sender_name, "item_bought")
            send_telegram_message(f"✅ Označeno kao kupljeno: <b>{joined_titles}</b>! Podsetnik je ugašen.", target_chat_id=chat_id)
        else:
            send_telegram_message(f"Nisam pronašao stavku '{query_val}' na aktivnom spisku. Napiši <i>„šta treba da se kupi”</i> za pregled.", target_chat_id=chat_id)
        return

    # 4. CHORES DONE ("sredio sam kupatilo", "oprao sudove", "bacio smece", "usisao stan")
    if any(w in normalized for w in ['sredio kupatilo', 'sredila kupatilo', 'ocistio kupatilo', 'ocistila kupatilo', 'kupatilo je sredjeno', 'sredio wc', 'ocistio wc', '/uradio kupatilo']):
        now_str = datetime.now().strftime("%d.%m. %H:%M")
        conn = get_db()
        c = conn.cursor()
        c.execute("UPDATE tasks SET is_completed_today=1, completed_by=?, last_completed_at=? WHERE zone='kupatilo'", (sender_name, now_str))
        conn.commit()
        conn.close()
        log_activity("Sredio/la kupatilo (100%)", sender_name, "task_done")
        send_telegram_message(f"🎉 <b>Svaka čast {sender_name}! Kupatilo je označeno kao 100% sređeno (4/4)!</b> ✅", target_chat_id=chat_id)
        return

    if any(w in normalized for w in ['oprao sudove', 'oprala sudove', 'oprani sudovi', 'sudovi reseni', 'napravio sudove']):
        conn = get_db()
        c = conn.cursor()
        c.execute("UPDATE tasks SET is_completed_today=1, completed_by=?, last_completed_at=? WHERE title LIKE '%sudov%'", (sender_name, datetime.now().strftime("%d.%m. %H:%M")))
        conn.commit()
        conn.close()
        send_telegram_message("🍽️ Sudovi su označeni kao oprani i sređeni! ✓", target_chat_id=chat_id)
        return

    if any(w in normalized for w in ['bacio smece', 'izneo smece', 'izbacio smece', 'bacio djubre', 'smece izneto']):
        conn = get_db()
        c = conn.cursor()
        c.execute("UPDATE tasks SET is_completed_today=1, completed_by=?, last_completed_at=? WHERE title LIKE '%smeć%'", (sender_name, datetime.now().strftime("%d.%m. %H:%M")))
        conn.commit()
        conn.close()
        send_telegram_message("🗑️ Iznošenje smeća označeno kao završeno! ✓", target_chat_id=chat_id)
        return

    if any(w in normalized for w in ['usisao', 'usisala', 'oprao podove', 'oprala podove', 'dzogirao', 'dzogirala', 'sredio podove']):
        conn = get_db()
        c = conn.cursor()
        c.execute("UPDATE tasks SET is_completed_today=1, completed_by=?, last_completed_at=? WHERE zone='podovi'", (sender_name, datetime.now().strftime("%d.%m. %H:%M")))
        conn.commit()
        conn.close()
        send_telegram_message("🔌 Podovi u celom stanu su označeni kao usisani i oprani (100%)! ✓", target_chat_id=chat_id)
        return

    if any(w in normalized for w in ['zategao krevet', 'namestio krevet', 'zategla krevet']):
        conn = get_db()
        c = conn.cursor()
        c.execute("UPDATE tasks SET is_completed_today=1, completed_by=?, last_completed_at=? WHERE title LIKE '%krevet%'", (sender_name, datetime.now().strftime("%d.%m. %H:%M")))
        conn.commit()
        conn.close()
        send_telegram_message("🛏️ Zatezanje kreveta označeno kao završeno! ✓", target_chat_id=chat_id)
        return

    # 5. URGENT ADD ("hitno kupi...", "hitno nam treba...", "bitno je da kupimo...")
    if any(w in normalized for w in ['hitno', 'bitno', 'vazno', 'urgentno']) and any(v in normalized for v in ['kupi', 'treba', 'fali', 'dodaj', 'nabavi', 'uzmi']):
        # Clean item name
        item_text = clean
        for prefix in ['hitno nam treba', 'hitno treba', 'hitno kupi', 'hitno dodaj', 'treba hitno', 'kupi hitno', 'bitno je da kupimo', 'bitno nam je', '/hitno']:
            if lower.startswith(prefix):
                item_text = clean[len(prefix):].strip()
                break

        if not item_text or item_text == clean:
            # Fallback regex
            m = re.search(r'\b(hitno|bitno)\b.*?\b(?:kupi|treba|dodaj|nabavi)\s+(.+)', clean, re.IGNORECASE)
            item_text = m.group(2).strip() if m else clean

        conn = get_db()
        c = conn.cursor()
        now_iso = datetime.now().isoformat()
        c.execute(
            "INSERT INTO shopping_items (title, category, quantity, added_by, is_bought, is_urgent, created_at, last_notified_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (item_text, "hitno", "1", sender_name, 0, 1, now_iso, now_iso)
        )
        conn.commit()
        conn.close()
        log_activity(f"Dodao/la HITNO: '{item_text}'", sender_name, "urgent_added")
        send_telegram_message(
            f"🚨 <b>Dodato u Hitno / Bitno:</b> {item_text}\n\n"
            f"⏰ <b>Aktiviran podsetnik:</b> Šaljem ti poruku <b>na svakih 30 minuta</b> (do 22:00) dok ne kupiš!\n"
            f"Kad kupiš, samo napiši npr: <i>„kupio sam {item_text}”</i>.",
            target_chat_id=chat_id
        )
        return

    # 6. REGULAR ADD ("kupi mleko", "dodaj hleb", "treba nam toalet papir", "fali nam...")
    add_match = re.search(r'^(?:kupi|dodaj|treba nam|fali nam|fali|nabavi|uzmi|upisi|zapisi)\s+(.+)', clean, re.IGNORECASE)
    if add_match or clean.startswith('/kupi'):
        item_text = add_match.group(1).strip() if add_match else clean[5:].strip()

        # Guess category
        low_item = item_text.lower()
        if any(w in low_item for w in ['omeksivac', 'omekšivač', 'hitno', 'bitno']):
            cat = "hitno"
            is_urg = 1
        elif any(w in low_item for w in ['domestos', 'cif', 'kamenac', 'wc', 'prasak', 'kapsule', 'ves', 'podove', 'stakla', 'sudove', 'deterdzent', 'sirce', 'soda', 'sapun']):
            cat = "hemija"
            is_urg = 0
        elif any(w in low_item for w in ['krp', 'kes', 'ubrus', 'sundjer', 'papir', 'baterij', 'sijalica']):
            cat = "potrepstine"
            is_urg = 0
        else:
            cat = "hrana"
            is_urg = 0

        conn = get_db()
        c = conn.cursor()
        c.execute(
            "INSERT INTO shopping_items (title, category, quantity, added_by, is_bought, is_urgent, created_at, last_notified_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (item_text, cat, "1", sender_name, 0, is_urg, datetime.now().isoformat(), datetime.now().isoformat() if is_urg else None)
        )
        conn.commit()
        conn.close()

        log_activity(f"Dodao/la '{item_text}' ({cat})", sender_name, "item_added")
        icon = "🚨" if is_urg else ("🍏" if cat == "hrana" else ("🧼" if cat == "hemija" else "📦"))
        timer_str = "na svakih 30 min" if is_urg else "<b>na svaka 2 sata</b> (do 22h)"
        send_telegram_message(f"✓ {icon} <b>Dodato na spisak za kupovinu:</b> {item_text}\nKategorija: <i>{cat}</i>\n⏰ Podsetnik stiže {timer_str}.", target_chat_id=chat_id)
        return

    # 7. QUESTIONS / STATUS / SHOPPING LIST ("šta treba da se kupi", "kakav je status", "šta ima u frižideru")
    if any(w in normalized for w in ['sta treba da se kupi', 'sta fali', 'daj spisak', 'spisak za kupovinu', 'sta imamo na spisku', 'sta da kupim', 'nabavka', '/spisak', '/nabavka']):
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT id, title, category, quantity, is_urgent FROM shopping_items WHERE is_bought=0 ORDER BY is_urgent DESC, category, id DESC")
        items = c.fetchall()
        conn.close()

        if not items:
            send_telegram_message("🎉 Spisak je prazan, sve je kupljeno! Ako nešto zatreba, samo napiši <i>„kupi mleko”</i>.", target_chat_id=chat_id)
            return

        reply = "🛒 <b>TRENUTNI SPISAK ZA NABAVKU:</b>\n\n"
        for idx, item in enumerate(items, 1):
            if item["is_urgent"] == 1 or item["category"] == "hitno":
                icon = "🚨 [HITNO 30m]"
            elif item["category"] == "hrana":
                icon = "🍏"
            elif item["category"] == "hemija":
                icon = "🧼"
            else:
                icon = "📦"
            reply += f"{idx}. {icon} {item['title']} ({item['quantity']})\n"

        pub_url = get_public_url()
        reply += f"\n💡 Kad kupiš, samo napiši npr: <i>„kupio sam {items[0]['title']}”</i>!\n🔗 {pub_url}"
        send_telegram_message(reply, target_chat_id=chat_id)
        return

    if any(w in normalized for w in ['status', 'kako stojimo', 'sta ima od poslova', 'poslovi za danas', 'zadaci za danas', '/status', '/zadaci']):
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT zone, COUNT(*) as total, SUM(is_completed_today) as done FROM tasks GROUP BY zone")
        rows = c.fetchall()
        c.execute("SELECT COUNT(*) FROM shopping_items WHERE is_bought=0 AND (is_urgent=1 OR category='hitno')")
        urg_count = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM shopping_items WHERE is_bought=0 AND is_urgent=0 AND category!='hitno'")
        reg_count = c.fetchone()[0]
        conn.close()

        zone_names = {
            'kupatilo': '🚿 Kupatilo',
            'dnevno': '✨ Dnevno & Provere',
            'sobe': '🛌 Sobe & Veš',
            'dnevna': '🛋️ Dnevna soba',
            'podovi': '🔌 Podovi',
            'dubinsko': '🔥 Dubinsko'
        }

        reply = f"📊 <b>STATUS DOMAĆINSTVA ZA DANAS:</b>\n\n"
        for r in rows:
            z = r["zone"]
            tot = r["total"]
            done = r["done"] or 0
            pct = int((done / tot) * 100) if tot > 0 else 0
            bar = "✅" if pct == 100 else ("⏳" if pct > 0 else "○")
            reply += f"{bar} <b>{zone_names.get(z, z)}:</b> {pct}% ({done}/{tot})\n"

        reply += f"\n🛒 <b>ZA KUPOVINU:</b>\n"
        reply += f"• 🚨 <b>Hitno:</b> {urg_count} stavki (podsetnik na 30 min)\n"
        reply += f"• 🍏 <b>Standardno:</b> {reg_count} stavki (podsetnik na 2h)\n\n"
        pub_url = get_public_url()
        reply += f"🔗 {pub_url}"
        send_telegram_message(reply, target_chat_id=chat_id)
        return

    if any(w in normalized for w in ['proveri', 'frizider', 'frizideru', 'provera', '/proveri']):
        reply = (
            "🔍 <b>KUĆNA PROVERA & INVENTAR:</b>\n\n"
            "Baci pogled po stanu i proveri ključne stvari:\n\n"
            "🧊 <b>1. Frižider:</b> Mleko, jaja, sir, hleb, meso, povrće?\n"
            "🍽️ <b>2. Kuhinja:</b> Sudovi oprani / mašina puna?\n"
            "🚽 <b>3. Kupatilo:</b> Čist WC i lavabo? Toalet papir i sapun?\n"
            "🧺 <b>4. Veš & Hemija:</b> <u>Ima li omekšivača za veš</u> i praška?\n"
            "🗑️ <b>5. Potrepštine:</b> Kese za smeće (60L), ubrusi, tablete za sudove?\n\n"
            "💡 <b>Ako nešto fali, samo mi napiši:</b>\n"
            "• <i>„hitno nam treba omekšivač”</i>\n"
            "• <i>„kupi mleko”</i>"
        )
        send_telegram_message(reply, target_chat_id=chat_id)
        return

    # Fallback response for unparsed messages
    send_telegram_message(
        f"Razumeo sam poruku: <i>„{clean}”</i>.\n\n"
        f"Možeš mi reći:\n"
        f"• <b>„kupi {clean}”</b> — dodaje na spisak za nabavku\n"
        f"• <b>„hitno nam treba {clean}”</b> — stavlja u hitno (podsetnik na 30m)\n"
        f"• <b>„kupio sam {clean}”</b> — označava kao kupljeno\n"
        f"• <b>„šta treba da se kupi”</b> — prikazuje ceo spisak",
        target_chat_id=chat_id
    )

# DUAL NOTIFIER (30 min urgent, 2 HOURS regular, quiet hours after 22:00)
def periodic_notification_worker():
    print("[Notifier] Pokrenut sistem podsetnika: 30min za hitno, 2 SATA za standardnu nabavku (Pauza posle 22:00).")
    while True:
        try:
            now = datetime.now()
            now_ts = int(time.time())

            conn = get_db()
            c = conn.cursor()

            c.execute("SELECT value FROM settings WHERE key='notifications_enabled'")
            notif_en_row = c.fetchone()
            notifications_enabled = notif_en_row[0] if notif_en_row else "1"

            if notifications_enabled == "0":
                conn.close()
                time.sleep(30)
                continue

            # Quiet hours: 22:00 to 08:30 (no notifications when stores are closed)
            if is_in_quiet_hours(now):
                conn.close()
                time.sleep(60)
                continue

            c.execute("SELECT value FROM settings WHERE key='last_urgent_notify'")
            u_row = c.fetchone()
            c.execute("SELECT value FROM settings WHERE key='last_regular_notify'")
            r_row = c.fetchone()

            last_u = int(u_row[0]) if u_row and u_row[0] else 0
            last_r = int(r_row[0]) if r_row and r_row[0] else 0

            # CHECK URGENT ITEMS (Every 30 mins = 1800s)
            c.execute("SELECT id, title, quantity FROM shopping_items WHERE is_bought=0 AND (is_urgent=1 OR category='hitno')")
            urgent_items = c.fetchall()

            if urgent_items and (now_ts - last_u >= 1800):
                msg = "🚨 <b>HITAN PODSETNIK (Ponavlja se na svakih 30 MINUTA):</b>\n\n"
                msg += "Sledeće bitne stvari <b>još uvek nisu kupljene</b>:\n"
                for it in urgent_items:
                    msg += f"• <b>{it['title']}</b> ({it['quantity']})\n"
                msg += f"\n💡 <i>Kad kupiš, samo napiši <b>„kupio sam {urgent_items[0]['title']}”</b> da ugasim podsetnik!</i>"
                success, _ = send_telegram_message(msg)
                if success:
                    c.execute("UPDATE settings SET value=? WHERE key='last_urgent_notify'", (str(now_ts),))
                    conn.commit()

            # CHECK REGULAR ITEMS (Every 2 HOURS = 7200s)
            c.execute("SELECT id, title, quantity, category FROM shopping_items WHERE is_bought=0 AND is_urgent=0 AND category!='hitno'")
            reg_items = c.fetchall()

            if reg_items and (now_ts - last_r >= 7200):
                msg = "🛒 <b>PODSETNIK ZA NABAVKU (Ponavlja se na svaka 2 SATA):</b>\n\n"
                msg += f"Na spisku te čeka <b>{len(reg_items)} stavki</b>:\n"
                for it in reg_items[:6]:
                    msg += f"• {it['title']} ({it['quantity']})\n"
                if len(reg_items) > 6:
                    msg += f"<i>...i još {len(reg_items) - 6} stavki.</i>\n"
                msg += f"\n💡 <i>Napiši <b>„kupio sam &lt;stavka&gt;”</b> ili proveri spisak na sajtu.</i>"
                success, _ = send_telegram_message(msg)
                if success:
                    c.execute("UPDATE settings SET value=? WHERE key='last_regular_notify'", (str(now_ts),))
                    conn.commit()

            conn.close()

        except Exception as e:
            print(f"[Periodic notifier error]: {e}")

        time.sleep(45)

# Smart Midnight Reset Scheduler
def smart_reset_scheduler_worker():
    while True:
        try:
            now = datetime.now()
            today_str = now.strftime("%Y-%m-%d")
            curr_hm = now.strftime("%H:%M")
            today_day_sr = DAYS_SR[now.weekday()]

            conn = get_db()
            c = conn.cursor()
            c.execute("SELECT value FROM settings WHERE key='reminder_time'")
            rem_row = c.fetchone()
            c.execute("SELECT value FROM settings WHERE key='last_reminder_date'")
            last_date_row = c.fetchone()
            c.execute("SELECT value FROM settings WHERE key='notifications_enabled'")
            notif_en_row = c.fetchone()
            conn.close()

            notifications_enabled = notif_en_row[0] if notif_en_row else "1"
            rem_time = rem_row[0] if rem_row else "09:00"
            last_date = last_date_row[0] if last_date_row else ""

            # Midnight reset
            if curr_hm == "00:01":
                conn = get_db()
                c = conn.cursor()
                c.execute("UPDATE tasks SET is_completed_today=0 WHERE recurrence='daily'")
                c.execute("UPDATE tasks SET is_completed_today=0 WHERE recurrence='weekly' AND room_day=?", (today_day_sr,))
                if now.day == 1:
                    c.execute("UPDATE tasks SET is_completed_today=0 WHERE recurrence='monthly'")

                conn.commit()
                conn.close()
                log_activity(f"Automatski reset zadataka za {today_day_sr}", "Sistem", "midnight_reset")

            # Morning Routine Briefing
            if curr_hm == rem_time and last_date != today_str and notifications_enabled == "1":
                focus_dict = {
                    "Ponedeljak": "📋 Plan nedelje & nabavka",
                    "Utorak": "🚿 Kupatilo i sanitarije (kamenac, WC, slavine)",
                    "Sreda": "🛌 Spavaća soba & posteljina & veš mašina",
                    "Četvrtak": "🧹 Dnevna soba & prašina & radni stolovi",
                    "Petak": "🔌 Podovi: Usisavanje i pranje celog stana",
                    "Subota": "☕ Lagani odmor ili 1 dubinski zadatak",
                    "Nedelja": "✨ Slobodan dan za uživanje u čistom stanu"
                }
                focus = focus_dict.get(today_day_sr, "Održavanje stana")

                conn = get_db()
                c = conn.cursor()
                c.execute("SELECT COUNT(*) FROM shopping_items WHERE is_bought=0")
                unbought_count = c.fetchone()[0]
                c.execute("SELECT COUNT(*) FROM shopping_items WHERE is_bought=0 AND (is_urgent=1 OR category='hitno')")
                urgent_count = c.fetchone()[0]
                conn.close()

                urg_alert = f"\n🚨 <b>HITNO ZA KUPOVINU:</b> {urgent_count} bitnih stavki!" if urgent_count > 0 else ""
                pub_url = get_public_url()
                msg = (
                    f"🌅 <b>Dobro jutro Miloše!</b> Danas je <b>{today_day_sr}</b>.\n\n"
                    f"🎯 <b>Fokus dana:</b> {focus}\n"
                    f"🛒 Na spisku za kupovinu: <b>{unbought_count} stavki</b>{urg_alert}\n\n"
                    f"💡 Napiši mi <i>„šta treba da se kupi”</i> ili <i>„kako stojimo”</i>!\n"
                    f"🔗 {pub_url}"
                )
                success, _ = send_telegram_message(msg)
                if success:
                    conn = get_db()
                    c = conn.cursor()
                    c.execute("UPDATE settings SET value=? WHERE key='last_reminder_date'", (today_str,))
                    conn.commit()
                    conn.close()

        except Exception as e:
            print(f"[Scheduler error]: {e}")

        time.sleep(30)

class RequestHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=PUBLIC_DIR, **kwargs)

    def do_GET(self):
        if self.path.startswith("/api/state"):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            conn = get_db()
            c = conn.cursor()
            c.execute("SELECT * FROM tasks ORDER BY recurrence DESC, id ASC")
            tasks = [dict(r) for r in c.fetchall()]

            c.execute("SELECT * FROM shopping_items ORDER BY is_bought ASC, is_urgent DESC, id DESC")
            shopping = [dict(r) for r in c.fetchall()]

            c.execute("SELECT * FROM users")
            users = [dict(r) for r in c.fetchall()]

            c.execute("SELECT * FROM activity_log ORDER BY id DESC LIMIT 25")
            activity = [dict(r) for r in c.fetchall()]

            c.execute("SELECT key, value FROM settings")
            settings = {r["key"]: r["value"] for r in c.fetchall()}

            zone_stats = {}
            for t in tasks:
                z = t["zone"]
                if z not in zone_stats:
                    zone_stats[z] = {"total": 0, "completed": 0, "pct": 0}
                zone_stats[z]["total"] += 1
                if t["is_completed_today"] == 1:
                    zone_stats[z]["completed"] += 1

            for z, s in zone_stats.items():
                s["pct"] = int((s["completed"] / s["total"]) * 100) if s["total"] > 0 else 0

            conn.close()

            now = datetime.now()
            today_day = DAYS_SR[now.weekday()]
            data = {
                "tasks": tasks,
                "shopping": shopping,
                "users": users,
                "activity": activity,
                "settings": settings,
                "zone_stats": zone_stats,
                "in_quiet_hours": is_in_quiet_hours(now),
                "public_url": get_public_url(),
                "local_ip": "192.168.0.11",
                "current_time": now.strftime("%H:%M"),
                "today_date": now.strftime("%d.%m.%Y"),
                "today_day_sr": today_day
            }
            self.wfile.write(json.dumps(data).encode("utf-8"))
            return

        if self.path == "/" or not os.path.exists(os.path.join(PUBLIC_DIR, self.path.lstrip("/"))):
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self):
        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len).decode("utf-8") if content_len > 0 else "{}"
        try:
            req_data = json.loads(body)
        except Exception:
            req_data = {}

        response = {"ok": True}

        if self.path == "/api/settings/toggle_notifications":
            conn = get_db()
            c = conn.cursor()
            c.execute("SELECT value FROM settings WHERE key='notifications_enabled'")
            curr = c.fetchone()
            new_val = "0" if curr and curr[0] == "1" else "1"
            c.execute("UPDATE settings SET value=? WHERE key='notifications_enabled'", (new_val,))
            conn.commit()
            conn.close()

            action_text = "Aktivirao/la notifikacije od bota" if new_val == "1" else "Pauzirao/la notifikacije od bota"
            log_activity(action_text, "Miloš", "notif_toggle")
            response = {"ok": True, "notifications_enabled": new_val}

        elif self.path == "/api/tasks/toggle":
            task_id = req_data.get("id")
            user_name = req_data.get("user_name", "Miloš")
            conn = get_db()
            c = conn.cursor()
            c.execute("SELECT title, is_completed_today FROM tasks WHERE id=?", (task_id,))
            task = c.fetchone()
            if task:
                new_state = 0 if task["is_completed_today"] == 1 else 1
                completed_by = user_name if new_state == 1 else None
                now_str = datetime.now().strftime("%d.%m. %H:%M") if new_state == 1 else None

                c.execute(
                    "UPDATE tasks SET is_completed_today=?, completed_by=?, last_completed_at=? WHERE id=?",
                    (new_state, completed_by, now_str, task_id)
                )
                conn.commit()
                conn.close()

                verb = "završio/la" if new_state == 1 else "vratio/la"
                log_activity(f"{verb}: '{task['title']}'", user_name, "task_toggle")
            else:
                conn.close()

        elif self.path == "/api/tasks/edit":
            task_id = req_data.get("id")
            title = req_data.get("title", "").strip()
            zone = req_data.get("zone", "dnevno")
            if task_id and title:
                conn = get_db()
                c = conn.cursor()
                c.execute("UPDATE tasks SET title=?, zone=? WHERE id=?", (title, zone, task_id))
                conn.commit()
                conn.close()
                log_activity(f"Izmenio/la zadatak #{task_id}: '{title}'", "Miloš", "task_edited")

        elif self.path == "/api/tasks/add":
            title = req_data.get("title", "").strip()
            zone = req_data.get("zone", "dnevno")
            recurrence = req_data.get("recurrence", "daily")
            user_name = req_data.get("user_name", "Miloš")
            if title:
                conn = get_db()
                c = conn.cursor()
                c.execute(
                    "INSERT INTO tasks (title, zone, recurrence, icon, frequency_days, room_day) VALUES (?, ?, ?, ?, ?, ?)",
                    (title, zone, recurrence, "✨", 1, "Dodato")
                )
                conn.commit()
                conn.close()
                log_activity(f"Dodao/la zadatak: '{title}'", user_name, "task_added")

        elif self.path == "/api/tasks/delete":
            task_id = req_data.get("id")
            conn = get_db()
            c = conn.cursor()
            c.execute("DELETE FROM tasks WHERE id=?", (task_id,))
            conn.commit()
            conn.close()

        elif self.path == "/api/shopping/add":
            title = req_data.get("title", "").strip()
            category = req_data.get("category", "hrana")
            quantity = req_data.get("quantity", "1")
            is_urgent = 1 if req_data.get("is_urgent") or category == "hitno" else 0
            user_name = req_data.get("user_name", "Miloš")

            if title:
                now_iso = datetime.now().isoformat()
                conn = get_db()
                c = conn.cursor()
                c.execute(
                    "INSERT INTO shopping_items (title, category, quantity, added_by, is_bought, is_urgent, created_at, last_notified_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (title, category, quantity, user_name, 0, is_urgent, now_iso, now_iso if is_urgent else None)
                )
                conn.commit()
                conn.close()
                log_activity(f"Dodao/la {'[HITNO] ' if is_urgent else ''}'{title}'", user_name, "item_added")

        elif self.path == "/api/shopping/edit":
            item_id = req_data.get("id")
            title = req_data.get("title", "").strip()
            quantity = req_data.get("quantity", "1")
            category = req_data.get("category", "hrana")
            is_urgent = 1 if req_data.get("is_urgent") or category == "hitno" else 0
            if item_id and title:
                conn = get_db()
                c = conn.cursor()
                c.execute("UPDATE shopping_items SET title=?, quantity=?, category=?, is_urgent=? WHERE id=?", (title, quantity, category, is_urgent, item_id))
                conn.commit()
                conn.close()

        elif self.path == "/api/shopping/delete":
            item_id = req_data.get("id")
            conn = get_db()
            c = conn.cursor()
            c.execute("DELETE FROM shopping_items WHERE id=?", (item_id,))
            conn.commit()
            conn.close()

        elif self.path == "/api/shopping/toggle_urgent":
            item_id = req_data.get("id")
            conn = get_db()
            c = conn.cursor()
            c.execute("SELECT title, is_urgent FROM shopping_items WHERE id=?", (item_id,))
            item = c.fetchone()
            if item:
                new_urg = 0 if item["is_urgent"] == 1 else 1
                now_iso = datetime.now().isoformat() if new_urg == 1 else None
                c.execute("UPDATE shopping_items SET is_urgent=?, last_notified_at=? WHERE id=?", (new_urg, now_iso, item_id))
                conn.commit()
                log_activity(f"{'Postavio kao HITNO' if new_urg == 1 else 'Uklonio iz hitnih'}: '{item['title']}'", "Sistem", "item_urgent_toggle")
            conn.close()

        elif self.path == "/api/shopping/toggle":
            item_id = req_data.get("id")
            user_name = req_data.get("user_name", "Miloš")
            conn = get_db()
            c = conn.cursor()
            c.execute("SELECT title, is_bought FROM shopping_items WHERE id=?", (item_id,))
            item = c.fetchone()
            if item:
                new_state = 0 if item["is_bought"] == 1 else 1
                now_str = datetime.now().strftime("%d.%m. %H:%M") if new_state == 1 else None
                bought_by = user_name if new_state == 1 else None

                c.execute(
                    "UPDATE shopping_items SET is_bought=?, bought_by=?, bought_at=? WHERE id=?",
                    (new_state, bought_by, now_str, item_id)
                )
                conn.commit()
                conn.close()

                verb = "kupio/la" if new_state == 1 else "vratio/la"
                log_activity(f"{verb}: '{item['title']}'", user_name, "item_bought")
            else:
                conn.close()

        elif self.path == "/api/shopping/clear_bought":
            conn = get_db()
            c = conn.cursor()
            c.execute("DELETE FROM shopping_items WHERE is_bought=1")
            conn.commit()
            conn.close()

        elif self.path == "/api/settings":
            conn = get_db()
            c = conn.cursor()
            for k in ["telegram_bot_token", "telegram_chat_id", "reminder_time", "active_user", "notifications_enabled"]:
                if k in req_data:
                    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (k, str(req_data[k]).strip()))
            conn.commit()
            conn.close()

        elif self.path == "/api/telegram/test":
            success, res = send_telegram_message("🔔 <b>Kućni Hub Test</b>\n\nTvoj lični Telegram je uspešno povezan! Sve notifikacije i komande rade direktno sa tobom. ✨")
            response = {"ok": success, "result": res}

        elif self.path == "/api/telegram/send_summary":
            conn = get_db()
            c = conn.cursor()
            c.execute("SELECT title, quantity, category, is_urgent FROM shopping_items WHERE is_bought=0 ORDER BY is_urgent DESC, id DESC")
            items = c.fetchall()
            conn.close()

            if not items:
                text = "🛒 <b>Spisak za kupovinu je prazan!</b> Sve je kupljeno. ✨"
            else:
                text = f"🛒 <b>SPISAK ZA KUPOVINU ({len(items)} stavki):</b>\n\n"
                for it in items:
                    icon = "🚨 [HITNO]" if it["is_urgent"] == 1 or it["category"] == "hitno" else ("🍏" if it["category"] == "hrana" else ("🧼" if it["category"] == "hemija" else "📦"))
                    text += f"• {icon} {it['title']} ({it['quantity']})\n"

            text += f"\n🔗 {get_public_url()}"
            success, res = send_telegram_message(text)
            response = {"ok": success, "result": res}

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(response).encode("utf-8"))

def run_server():
    init_db()

    # Telegram Poller
    t_telegram = threading.Thread(target=telegram_polling_worker, daemon=True)
    t_telegram.start()

    # Periodic Dual Notifier
    t_notifier = threading.Thread(target=periodic_notification_worker, daemon=True)
    t_notifier.start()

    # Smart Midnight Reset Scheduler
    t_scheduler = threading.Thread(target=smart_reset_scheduler_worker, daemon=True)
    t_scheduler.start()

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("0.0.0.0", PORT), RequestHandler) as httpd:
        pub = get_public_url()
        print(f"==================================================")
        print(f"🏠 KUĆNI HUB 7.0 AKTIVAN!")
        print(f"💻 Lokalno (MacBook): http://localhost:{PORT}")
        print(f"📱 Telefon (4G/5G bilo gde): {pub}")
        print(f"==================================================")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nZaustavljanje servera...")

if __name__ == "__main__":
    run_server()
