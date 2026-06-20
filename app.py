import os
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# Попытка импорта psycopg. Если не получится (нет БД), работаем в демо-режиме
try:
    import psycopg
    DB_AVAILABLE = True
except ImportError:
    DB_AVAILABLE = False
    print("WARNING: psycopg not found. Running in DEMO mode (no persistent DB).")

from flask import Flask, request, session, redirect, send_from_directory, render_template_string
from flask_socketio import SocketIO, emit, disconnect

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev_secret_key_123")
app.config['UPLOAD_FOLDER'] = 'static/avatars'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

# Создаем папку для аватарок при старте
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])
    print(f"Created directory: {app.config['UPLOAD_FOLDER']}")

socketio = SocketIO(app, async_mode="threading", manage_session=False)

# Получаем URL БД из переменных окружения
DATABASE_URL = os.environ.get("DATABASE_URL")

# ---------- THEMES (Обновлено) ----------
THEMES = {
    "dark": ("#111", "#fff"),
    "light": ("#eee", "#000"),
    "ash": ("#282a36", "#f8f8f2"),      # бывшая dracula
    "ocean": ("#002", "#0ff"),
    "aero": ("#80f6ff", "#003b44"),
    "candy": ("#ff80b3", "#4a001f"),
    "matrix": ("#000", "#209400"),
    "contrast_dark": ("#000", "#8400ff"),
    "contrast_light": ("#ffffff", "#cc1616"),
    "theatre": ("#242424", "#b8000c"),
    "fire": ("#2b0505", "#ff4500"),     # новая тема
}

# ---------- STATES & COUNTRIES ----------
US_STATES = {
    "": "No State",
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
    "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri",
    "MT": "Montana", "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey",
    "NM": "New Mexico", "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio",
    "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont",
    "VA": "Virginia", "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming"
}

COUNTRIES = [
    "Afghanistan", "Albania", "Algeria", "Andorra", "Angola", "Antigua and Barbuda", "Argentina", "Armenia",
    "Australia", "Austria", "Azerbaijan", "Bahamas", "Bahrain", "Bangladesh", "Barbados", "Belarus", "Belgium",
    "Belize", "Benin", "Bhutan", "Bolivia", "Bosnia and Herzegovina", "Botswana", "Brazil", "Brunei", "Bulgaria",
    "Burkina Faso", "Burundi", "Cabo Verde", "Cambodia", "Cameroon", "Canada", "Central African Republic", "Chad",
    "Chile", "China", "Colombia", "Comoros", "Congo (Brazzaville)", "Congo (Kinshasa)", "Costa Rica", "Croatia",
    "Cuba", "Cyprus", "Czechia", "Denmark", "Djibouti", "Dominica", "Dominican Republic", "Ecuador", "Egypt",
    "El Salvador", "Equatorial Guinea", "Eritrea", "Estonia", "Eswatini", "Ethiopia", "Fiji", "Finland", "France",
    "Gabon", "Gambia", "Georgia", "Germany", "Ghana", "Greece", "Grenada", "Guatemala", "Guinea", "Guinea-Bissau",
    "Guyana", "Haiti", "Honduras", "Hungary", "Iceland", "India", "Indonesia", "Iran", "Iraq", "Ireland", "Israel",
    "Italy", "Jamaica", "Japan", "Jordan", "Kazakhstan", "Kenya", "Kiribati", "Kuwait", "Kyrgyzstan", "Laos",
    "Latvia", "Lebanon", "Lesotho", "Liberia", "Libya", "Liechtenstein", "Lithuania", "Luxembourg", "Madagascar",
    "Malawi", "Malaysia", "Maldives", "Mali", "Malta", "Marshall Islands", "Mauritania", "Mauritius", "Mexico",
    "Micronesia", "Moldova", "Monaco", "Mongolia", "Montenegro", "Morocco", "Mozambique", "Myanmar", "Namibia",
    "Nauru", "Nepal", "Netherlands", "New Zealand", "Nicaragua", "Niger", "Nigeria", "North Korea", "North Macedonia",
    "Norfolk Island", "Norway", "Oman", "Pakistan", "Palau", "Palestine", "Panama", "Papua New Guinea", "Paraguay",
    "Peru", "Philippines", "Poland", "Portugal", "Qatar", "Romania", "Russia", "Rwanda", "Saint Kitts and Nevis",
    "Saint Lucia", "Saint Vincent and the Grenadines", "Samoa", "San Marino", "Sao Tome and Principe", "Saudi Arabia",
    "Senegal", "Serbia", "Seychelles", "Sierra Leone", "Singapore", "Slovakia", "Slovenia", "Solomon Islands",
    "Somalia", "South Africa", "South Korea", "South Sudan", "Spain", "Sri Lanka", "Sudan", "Suriname", "Sweden",
    "Switzerland", "Syria", "Tajikistan", "Tanzania", "Thailand", "Timor-Leste", "Togo", "Tonga", "Trinidad and Tobago",
    "Tunisia", "Turkey", "Turkmenistan", "Tuvalu", "Uganda", "Ukraine", "United Arab Emirates", "United Kingdom",
    "United States", "Uruguay", "Uzbekistan", "Vanuatu", "Vatican City", "Venezuela", "Vietnam", "Yemen", "Zambia",
    "Zimbabwe", "Antarctica"
]

# Часовые пояса от -12 до +14
TIMEZONES = []
for i in range(-12, 15):
    if i == 0:
        TIMEZONES.append("UTC")
    elif i > 0:
        TIMEZONES.append(f"Etc/GMT-{i}") # Знак минус в названии Etc/GMT означает плюс к UTC
    else:
        TIMEZONES.append(f"Etc/GMT+{-i}")

# Демо-хранилище (если БД недоступна)
DEMO_USERS = {}
DEMO_MESSAGES = []
DEMO_FRIENDSHIPS = []
MODERATORS = set()
BANNED_USERS = set()
MUTED_USERS = {} # {user_id: expire_time}

def get_db():
    if not DB_AVAILABLE or not DATABASE_URL:
        return None
    try:
        conn = psycopg.connect(DATABASE_URL)
        return conn
    except Exception as e:
        print(f"DB Connection Error: {e}")
        return None

def init_db():
    db = get_db()
    if not db: return
    
    c = db.cursor()
    try:
        c.execute("""
        CREATE TABLE IF NOT EXISTS users(
          id SERIAL PRIMARY KEY,
          username TEXT UNIQUE,
          password TEXT,
          nickname TEXT,
          avatar TEXT,
          country TEXT DEFAULT 'United States',
          state TEXT DEFAULT '',
          theme TEXT DEFAULT 'matrix',
          timezone TEXT DEFAULT 'UTC',
          is_moderator BOOLEAN DEFAULT FALSE
        )
        """)
        c.execute("""
        CREATE TABLE IF NOT EXISTS messages(
          id SERIAL PRIMARY KEY,
          user_id INTEGER,
          content TEXT,
          created_at TIMESTAMPTZ DEFAULT NOW()
        )
        """)
        c.execute("""
        CREATE TABLE IF NOT EXISTS friendships(
          user_id INTEGER,
          friend_id INTEGER,
          PRIMARY KEY (user_id, friend_id)
        )
        """)
        db.commit()
        print("Database initialized successfully.")
    except Exception as e:
        print(f"DB Init Error: {e}")
    finally:
        db.close()

if DB_AVAILABLE and DATABASE_URL:
    init_db()

# ---------- AUTH ----------

@app.route("/", methods=["GET","POST"])
def login():
    if request.method=="POST":
        u = request.form["username"]
        p = request.form["password"]
        
        db = get_db()
        if db:
            c = db.cursor()
            c.execute("SELECT id, username, password FROM users WHERE username=%s AND password=%s",(u,p))
            r = c.fetchone()
            db.close()
            if r:
                session["user_id"] = r[0]
                return redirect("/chat")
        else:
            # Demo mode login
            for uid, data in DEMO_USERS.items():
                if data['username'] == u and data['password'] == p:
                    session["user_id"] = uid
                    return redirect("/chat")
        
        return "Invalid credentials", 401
        
    return """
    <form method=post style="background:#000;color:#0f0;padding:20px;font-family:monospace">
      <h3>Login</h3>
      <input name=username placeholder="Username"><br><br>
      <input name=password type=password placeholder="Password"><br><br>
      <button>Login</button>
    </form>
    <a href=/register style="color:#0f0;margin-left:20px">Register</a>
    """

@app.route("/register", methods=["GET","POST"])
def register():
    if request.method=="POST":
        db = get_db()
        username = request.form["username"]
        password = request.form["password"]
        country = request.form.get("country", "United States")
        state = request.form.get("state", "")
        avatar_file = request.files.get("avatar_file")
        
        avatar_name = ""
        if avatar_file and avatar_file.filename != '':
            ext = avatar_file.filename.rsplit('.', 1)[1].lower() if '.' in avatar_file.filename else 'png'
            avatar_name = f"u_{uuid.uuid4().hex[:8]}.{ext}"
            avatar_file.save(os.path.join(app.config['UPLOAD_FOLDER'], avatar_name))

        if db:
            c = db.cursor()
            try:
                c.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM users")
                new_id = c.fetchone()[0]
                
                is_mod = (username == "Dfghj")
                
                c.execute("""
                  INSERT INTO users(id, username, password, avatar, country, state, theme, timezone, is_moderator)
                  VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """, (new_id, username, password, avatar_name, country, state, 'matrix', 'UTC', is_mod))
                db.commit()
                db.close()
                return redirect("/")
            except Exception as e:
                db.close()
                return f"Error: {str(e)}", 400
        else:
            # Demo mode
            new_id = len(DEMO_USERS) + 1
            DEMO_USERS[new_id] = {
                "username": username, "password": password, "avatar": avatar_name,
                "country": country, "state": state, "theme": "matrix", "timezone": "UTC",
                "nickname": username, "is_moderator": (username == "Dfghj")
            }
            if username == "Dfghj":
                MODERATORS.add(new_id)
            return redirect("/")

    # Генерация опций
    country_opts = "".join([f'<option value="{c}" {"selected" if c=="United States" else ""}>{c}</option>' for c in COUNTRIES])
    tz_opts = "".join([f'<option value="{t}">{t}</option>' for t in TIMEZONES])
    
    return f"""
    <body style="background:#000;color:#0f0;font-family:monospace;padding:20px">
    <h3>Register</h3>
    <form method=post enctype="multipart/form-data">
      Username: <input name=username required><br><br>
      Password: <input name=password type=password required><br><br>
      Country: <select name=country id="countrySelect" onchange="toggleState()">{country_opts}</select><br><br>
      
      <div id="stateDiv" style="display:none">
        State: <select name=state>
          <option value="">No State</option>
          {"".join([f'<option value="{k}">{v}</option>' for k,v in US_STATES.items() if k != ""])}
        </select><br><br>
      </div>
      
      Avatar (optional): <input type=file name=avatar_file accept="image/*"><br><br>
      <button>Register</button>
    </form>
    <script>
      function toggleState() {{
        const sel = document.getElementById('countrySelect');
        const div = document.getElementById('stateDiv');
        if(sel.value === 'United States') div.style.display = 'block';
        else div.style.display = 'none';
      }}
      // Init
      toggleState();
    </script>
    </body>
    """

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# ---------- SOCKET & CHAT LOGIC ----------

connected_users = {}

@socketio.on('connect')
def handle_connect():
    uid = session.get('user_id')
    if uid is None:
        disconnect()
        return False
    connected_users[request.sid] = uid
    print(f"User {uid} connected")

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    if sid in connected_users:
        del connected_users[sid]

@socketio.on("msg")
def handle_msg(text):
    user_id = connected_users.get(request.sid)
    if user_id is None: return

    # Проверка бана
    if user_id in BANNED_USERS:
        emit("error", "You are banned!")
        return
    
    # Проверка мута
    if user_id in MUTED_USERS:
        if datetime.now() < MUTED_USERS[user_id]:
            emit("error", "You are muted!")
            return
        else:
            del MUTED_USERS[user_id]

    # Обработка команд модератора
    if text.startswith("/"):
        process_command(user_id, text)
        return

    db = get_db()
    msg_data = {}

    if db:
        c = db.cursor()
        c.execute("SELECT nickname, avatar, country, state, timezone FROM users WHERE id=%s", (user_id,))
        row = c.fetchone()
        if not row: 
            db.close()
            return
        nick, avatar, country, state, tz = row
        
        c.execute("INSERT INTO messages(user_id, content) VALUES(%s,%s)", (user_id, text))
        db.commit()
        db.close()
        
        now = datetime.now(ZoneInfo(tz)).strftime("%H:%M:%S")
        msg_data = {"nick": nick, "avatar": avatar, "text": text, "time": now, "user_id": user_id, "country": country, "state": state}
    else:
        # Demo mode
        u = DEMO_USERS.get(user_id, {})
        nick = u.get("nickname", u.get("username"))
        avatar = u.get("avatar", "")
        country = u.get("country", "United States")
        state = u.get("state", "")
        tz = u.get("timezone", "UTC")
        
        now = datetime.now(ZoneInfo(tz)).strftime("%H:%M:%S")
        msg_data = {"nick": nick, "avatar": avatar, "text": text, "time": now, "user_id": user_id, "country": country, "state": state}
        DEMO_MESSAGES.append(msg_data)

    # Используем безопасно экранированную строку для флагов
    msg_data['flags_html'] = get_flags_html_safe(msg_data['country'], msg_data['state'])
    emit("msg", msg_data, broadcast=True)

def process_command(user_id, text):
    parts = text.split()
    cmd = parts[0]
    
    db = get_db()
    is_mod = False
    
    if db:
        c = db.cursor()
        c.execute("SELECT is_moderator, username FROM users WHERE id=%s", (user_id,))
        res = c.fetchone()
        if res:
            is_mod = res[0]
            username = res[1]
        db.close()
    else:
        is_mod = user_id in MODERATORS
        username = DEMO_USERS.get(user_id, {}).get("username", "")

    if not is_mod:
        emit("error", "Not authorized")
        return

    if cmd == "/clear":
        if db:
            conn = get_db()
            c = conn.cursor()
            c.execute("DELETE FROM messages")
            conn.commit()
            conn.close()
        else:
            DEMO_MESSAGES.clear()
        emit("sys", "Chat cleared by moderator", broadcast=True)
        
    elif cmd == "/ban" and len(parts) > 1:
        target = parts[1].replace("@", "")
        try:
            tid = int(target)
            BANNED_USERS.add(tid)
            emit("sys", f"User {tid} has been banned", broadcast=True)
        except: pass

    elif cmd == "/mute" and len(parts) > 2:
        target = parts[1].replace("@", "")
        try:
            tid = int(target)
            hours = int(parts[2])
            MUTED_USERS[tid] = datetime.now().replace(microsecond=0) + timedelta(hours=hours)
            emit("sys", f"User {tid} muted for {hours} hours", broadcast=True)
        except: pass

    elif cmd == "/del" and len(parts) > 1:
        if username == "Dfghj":
            target = parts[1].replace("@", "")
            try:
                tid = int(target)
                if db:
                    conn = get_db()
                    c = conn.cursor()
                    c.execute("DELETE FROM users WHERE id=%s", (tid,))
                    c.execute("DELETE FROM messages WHERE user_id=%s", (tid,))
                    conn.commit()
                    conn.close()
                else:
                    if tid in DEMO_USERS: del DEMO_USERS[tid]
                emit("sys", f"User {tid} account deleted by Dfghj", broadcast=True)
            except: pass
        else:
            emit("error", "Only Dfghj can use /del")

# ---------- PAGES ----------

@app.route("/chat")
def chat():
    if "user_id" not in session: return redirect("/")
    
    uid = session["user_id"]
    db = get_db()
    user_info = {}
    messages = []
    friend_ids = []

    if db:
        c = db.cursor()
        c.execute("SELECT nickname, avatar, country, state, theme, timezone FROM users WHERE id=%s", (uid,))
        row = c.fetchone()
        if row:
            user_info = {"nick": row[0], "avatar": row[1], "country": row[2], "state": row[3], "theme": row[4], "tz": row[5]}
        
        c.execute("SELECT friend_id FROM friendships WHERE user_id=%s", (uid,))
        friend_ids = [r[0] for r in c.fetchall()]
        
        c.execute("""
            SELECT m.content, m.created_at, u.nickname, u.avatar, u.country, u.state, u.timezone, u.id
            FROM messages m JOIN users u ON m.user_id = u.id
            ORDER BY m.created_at ASC LIMIT 100
        """)
        for r in c.fetchall():
            local_time = r[1].astimezone(ZoneInfo(r[6])).strftime("%H:%M:%S")
            # Используем безопасно экранированную строку для флагов
            flags_html = get_flags_html_safe(r[4], r[5]) # country, state
            messages.append({
                "text": r[0], "time": local_time, "nick": r[2], "avatar": r[3],
                "country": r[4], "state": r[5], "user_id": r[7], "flags_html": flags_html
            })
        db.close()
    else:
        u = DEMO_USERS.get(uid, {})
        user_info = {"nick": u.get("nickname"), "avatar": u.get("avatar"), "country": u.get("country"), "state": u.get("state"), "theme": "matrix", "tz": "UTC"}
        messages = DEMO_MESSAGES[-100:]
        # Добавляем безопасные флаги для демо-сообщений
        for msg in messages:
            msg['flags_html'] = get_flags_html_safe(msg['country'], msg['state'])

    colors = THEMES.get(user_info.get("theme", "matrix"), THEMES["matrix"])
    
    # Рендер сообщений
    msgs_html = ""
    for m in messages:
        is_friend = m["user_id"] in friend_ids
        style = 'border: 2px solid #0f0; background: rgba(0,255,0,0.1); padding:5px;' if is_friend else ''
        
        # Теперь используем уже подготовленный HTML для флагов
        flags_html = m.get('flags_html', '')
        
        nick_link = f'<a href="/profile/{m["user_id"]}" style="color:inherit;text-decoration:none">{m["nick"]}</a>'
        msgs_html += f"""
        <div style="{style}">
          {flags_html}
          <b>{nick_link}</b> <small>({m["time"]})</small><br>
          {m["text"]}
        </div><br>
        """

    return f"""
    <!doctype html>
    <body style="margin:0;background:{colors[0]};color:{colors[1]};font-family:monospace">
    <div style="padding:10px;border-bottom:1px solid {colors[1]}">
      {user_info.get('nick')} | 
      <a href="/settings" style="color:{colors[1]}">Settings</a> |
      <a href="/leaderboard" style="color:{colors[1]}">Leaderboard</a> |
      <a href="/logout" style="color:{colors[1]}">Logout</a>
    </div>
    <div id="chat" style="height:75vh;overflow:auto;padding:10px">{msgs_html}</div>
    <div style="display:flex;padding:10px">
      <input id="msg" style="flex:1;background:{colors[0]};color:{colors[1]};border:1px solid {colors[1]}" onkeydown="if(event.key==='Enter')send()">
      <button onclick="send()" style="background:{colors[1]};color:{colors[0]}">Send</button>
    </div>
    <script src="https://cdn.socket.io/4.7.2/socket.io.min.js"></script>
    <script>
      const s = io();
      const friendIds = {friend_ids};
      
      s.on("msg", m => {{
        const isFriend = friendIds.includes(m.user_id);
        const style = isFriend ? 'border: 2px solid #0f0; background: rgba(0,255,0,0.1); padding:5px;' : '';
        // Используем заранее подготовленный HTML для флагов
        const flagsHtml = m.flags_html || ''; // Обеспечиваем безопасность
        const nickLink = `<a href="/profile/${{m.user_id}}" style="color:inherit;text-decoration:none">${{m.nick}}</a>`;
        
        const html = `<div style="${{style}}">${{flagsHtml}}<b>${{nickLink}}</b> <small>(${{m.time}})</small><br>${{m.text}}</div><br>`;
        document.getElementById('chat').innerHTML += html;
        document.getElementById('chat').scrollTop = document.getElementById('chat').scrollHeight;
      }});
      
      s.on("sys", msg => {{
         const html = `<div style="color:yellow;font-weight:bold">[SYSTEM]: ${{msg}}</div><br>`;
         document.getElementById('chat').innerHTML += html;
      }});
      
      s.on("error", msg => alert(msg));

      function send() {{
        const inp = document.getElementById('msg');
        if(inp.value.trim()) {{
          s.emit("msg", inp.value);
          inp.value = "";
        }}
      }}
    </script>
    </body>
    """

def get_flags_html_safe(country, state):
    """Безопасно генерирует HTML для флага, обрабатывая возможные ошибки."""
    if not country:
        return ""

    # Код страны для flagcdn (ISO 2 буквы)
    # Простая маппинг функция (можно расширить)
    country_codes = {
        "United States": "us", "United Kingdom": "gb", "Russia": "ru", "Germany": "de",
        "France": "fr", "China": "cn", "Japan": "jp", "Brazil": "br", "Canada": "ca",
        "Australia": "au", "India": "in", "Italy": "it", "Spain": "es", "Mexico": "mx",
        "South Korea": "kr", "Ukraine": "ua", "Poland": "pl", "Turkey": "tr"
        # Добавьте другие по необходимости, или используйте общий флаг если нет кода
    }

    code = country_codes.get(country, "")
    if not code:
        # Пытаемся сгенерировать код из названия (первые 2 буквы, грубо)
        # Убедимся, что строка содержит только допустимые символы для URL
        clean_country = ''.join(c for c in country if c.isalnum()).lower()
        if len(clean_country) >= 2:
            code = clean_country[:2]
        else:
             # Если очистка не дала результата, возвращаем пустую строку
             return ""

    # Экранируем код страны перед вставкой в HTML/JS
    code = code.replace('"', '&quot;').replace("'", "&#x27;")
    escaped_country = country.replace('"', '&quot;').replace("'", "&#x27;")

    flag_main = f'<img src="https://flagcdn.com/w40/{code}.png" style="vertical-align:middle;margin-right:5px" title="{escaped_country}">' if code else ''

    flag_state = ""
    if country == "United States" and state:
        # Убедимся, что state - это действительный код штата
        state_code = state.lower()
        if state_code in US_STATES:
            # Экранируем код штата перед вставкой
            state_code = state_code.replace('"', '&quot;').replace("'", "&#x27;")
            escaped_state_name = US_STATES[state].replace('"', '&quot;').replace("'", "&#x27;")
            flag_state = f'<img src="https://flagcdn.com/w40/{state_code}.png" style="vertical-align:middle;margin-left:5px" title="{escaped_state_name}">'

    return f"{flag_main}{flag_state}"

@app.route("/profile/<int:user_id>")
def profile(user_id):
    # Заглушка профиля, можно доработать аналогично чату
    return f"<body style='background:#000;color:#0f0;font-family:monospace'><a href='/chat'>Back</a><h3>User Profile {user_id}</h3></body>"

@app.route("/settings", methods=["GET","POST"])
def settings():
    if "user_id" not in session: return redirect("/")
    uid = session["user_id"]
    db = get_db()
    
    if request.method == "POST":
        nick = request.form.get("nickname")
        country = request.form.get("country")
        state = request.form.get("state")
        theme = request.form.get("theme")
        tz = request.form.get("timezone")
        avatar_file = request.files.get("avatar_file")
        
        avatar_name = None
        if avatar_file and avatar_file.filename != '':
            ext = avatar_file.filename.rsplit('.', 1)[1].lower() if '.' in avatar_file.filename else 'png'
            avatar_name = f"u_{uuid.uuid4().hex[:8]}.{ext}"
            avatar_file.save(os.path.join(app.config['UPLOAD_FOLDER'], avatar_name))
            
        if db:
            c = db.cursor()
            if avatar_name:
                c.execute("UPDATE users SET nickname=%s, country=%s, state=%s, theme=%s, timezone=%s, avatar=%s WHERE id=%s",
                          (nick, country, state, theme, tz, avatar_name, uid))
            else:
                c.execute("UPDATE users SET nickname=%s, country=%s, state=%s, theme=%s, timezone=%s WHERE id=%s",
                          (nick, country, state, theme, tz, uid))
            db.commit()
            db.close()
        else:
            u = DEMO_USERS[uid]
            u["nickname"] = nick
            u["country"] = country
            u["state"] = state
            u["theme"] = theme
            u["timezone"] = tz
            if avatar_name: u["avatar"] = avatar_name
            
        return redirect("/chat")

    user = {}
    if db:
        c = db.cursor()
        c.execute("SELECT nickname, avatar, country, state, theme, timezone FROM users WHERE id=%s", (uid,))
        r = c.fetchone()
        if r: user = {"nick": r[0], "avatar": r[1], "country": r[2], "state": r[3], "theme": r[4], "tz": r[5]}
        db.close()
    else:
        user = DEMO_USERS.get(uid, {})

    country_opts = "".join([f'<option value="{c}" {"selected" if c==user.get("country") else ""}>{c}</option>' for c in COUNTRIES])
    tz_opts = "".join([f'<option value="{t}" {"selected" if t==user.get("tz") else ""}>{t}</option>' for t in TIMEZONES])
    theme_opts = "".join([f'<option value="{t}" {"selected" if t==user.get("theme") else ""}>{t}</option>' for t in THEMES.keys()])
    
    state_opts = "".join([f'<option value="{k}" {"selected" if k==user.get("state") else ""}>{v}</option>' for k,v in US_STATES.items()])

    return f"""
    <body style="background:#000;color:#0f0;font-family:monospace;padding:20px">
    <h3>Settings</h3>
    <form method=post enctype="multipart/form-data">
      Nickname: <input name=nickname value="{user.get('nick', '')}"><br><br>
      Country: <select name=country id="countrySelect" onchange="toggleState()">{country_opts}</select><br><br>
      
      <div id="stateDiv" style="display:{'block' if user.get('country')=='United States' else 'none'}">
        State: <select name=state>{state_opts}</select><br><br>
      </div>
      
      Theme: <select name=theme>{theme_opts}</select><br><br>
      Timezone: <select name=timezone>{tz_opts}</select><br><br>
      New Avatar: <input type=file name=avatar_file accept="image/*"><br><br>
      <button>Save</button>
    </form>
    <a href="/chat">Back</a>
    <script>
      function toggleState() {{
        const sel = document.getElementById('countrySelect');
        const div = document.getElementById('stateDiv');
        div.style.display = (sel.value === 'United States') ? 'block' : 'none';
      }}
    </script>
    </body>
    """

@app.route("/leaderboard")
def leaderboard():
    db = get_db()
    rows = []
    if db:
        c = db.cursor()
        c.execute("""
            SELECT u.username, COUNT(m.id) as cnt
            FROM users u LEFT JOIN messages m ON u.id = m.user_id
            GROUP BY u.id ORDER BY cnt DESC
        """)
        rows = c.fetchall()
        db.close()
    else:
        # Demo count
        counts = {}
        for m in DEMO_MESSAGES:
            uid = m.get("user_id")
            counts[uid] = counts.get(uid, 0) + 1
        for uid, data in DEMO_USERS.items():
            rows.append((data["username"], counts.get(uid, 0)))
        rows.sort(key=lambda x: x[1], reverse=True)

    html = "<body style='background:#000;color:#0f0;font-family:monospace;padding:20px'><h3>Leaderboard</h3><ol>"
    for name, cnt in rows:
        html += f"<li>{name}: {cnt} messages</li>"
    html += "</ol><a href='/chat'>Back to Chat</a></body>"
    return html

@app.route("/static/avatars/<path:filename>")
def serve_avatar(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"Starting server on port {port}")
    socketio.run(app, host="0.0.0.0", port=port, debug=False, allow_unsafe_werkzeug=True)
