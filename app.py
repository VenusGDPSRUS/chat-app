import os
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from flask import Flask, request, session, redirect, send_from_directory, render_template_string
from flask_socketio import SocketIO, emit, disconnect

# Попытка импорта psycopg. Если не выйдет (нет БД), ставим заглушку
try:
    import psycopg
    DB_AVAILABLE = True
except ImportError:
    DB_AVAILABLE = False
    psycopg = None

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-prod")
app.config['UPLOAD_FOLDER'] = 'static/avatars'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

# Создаем папку для аватарок при старте
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

socketio = SocketIO(app, async_mode="threading", manage_session=False)

# Глобальные переменные для демо-режима (если БД нет)
DEMO_USERS = {}  # id -> {username, password, nickname, avatar, theme, timezone, country, state}
DEMO_MESSAGES = [] # list of message dicts
DEMO_FRIENDS = set() # tuple (user_id, friend_id)
DEMO_BANS = {} # user_id -> None (permaban) or datetime (mute end)
NEXT_DEMO_ID = 1

# Список часовых поясов (упрощенный: от -12 до +14)
TIMEZONES = []
for i in range(-12, 15):
    if i == 0:
        TIMEZONES.append("UTC")
    elif i > 0:
        TIMEZONES.append(f"Etc/GMT-{i}") # Знак минус в названии Etc/GMT означает плюс к времени
    else:
        TIMEZONES.append(f"Etc/GMT+{abs(i)}")

# Список стран и коды флагов (ISO 3166-1 alpha-2)
COUNTRIES = {
    "Afghanistan": "af", "Albania": "al", "Algeria": "dz", "Andorra": "ad", "Angola": "ao",
    "Antigua and Barbuda": "ag", "Argentina": "ar", "Armenia": "am", "Australia": "au", "Austria": "at",
    "Azerbaijan": "az", "Bahamas": "bs", "Bahrain": "bh", "Bangladesh": "bd", "Barbados": "bb",
    "Belarus": "by", "Belgium": "be", "Belize": "bz", "Benin": "bj", "Bhutan": "bt",
    "Bolivia": "bo", "Bosnia and Herzegovina": "ba", "Botswana": "bw", "Brazil": "br", "Brunei": "bn",
    "Bulgaria": "bg", "Burkina Faso": "bf", "Burundi": "bi", "Cabo Verde": "cv", "Cambodia": "kh",
    "Cameroon": "cm", "Canada": "ca", "Central African Republic": "cf", "Chad": "td", "Chile": "cl",
    "China": "cn", "Colombia": "co", "Comoros": "km", "Congo (Brazzaville)": "cg", "Congo (Kinshasa)": "cd",
    "Costa Rica": "cr", "Croatia": "hr", "Cuba": "cu", "Cyprus": "cy", "Czechia": "cz",
    "Denmark": "dk", "Djibouti": "dj", "Dominica": "dm", "Dominican Republic": "do", "Ecuador": "ec",
    "Egypt": "eg", "El Salvador": "sv", "Equatorial Guinea": "gq", "Eritrea": "er", "Estonia": "ee",
    "Eswatini": "sz", "Ethiopia": "et", "Fiji": "fj", "Finland": "fi", "France": "fr",
    "Gabon": "ga", "Gambia": "gm", "Georgia": "ge", "Germany": "de", "Ghana": "gh",
    "Greece": "gr", "Grenada": "gd", "Guatemala": "gt", "Guinea": "gn", "Guinea-Bissau": "gw",
    "Guyana": "gy", "Haiti": "ht", "Honduras": "hn", "Hungary": "hu", "Iceland": "is",
    "India": "in", "Indonesia": "id", "Iran": "ir", "Iraq": "iq", "Ireland": "ie",
    "Israel": "il", "Italy": "it", "Jamaica": "jm", "Japan": "jp", "Jordan": "jo",
    "Kazakhstan": "kz", "Kenya": "ke", "Kiribati": "ki", "Kuwait": "kw", "Kyrgyzstan": "kg",
    "Laos": "la", "Latvia": "lv", "Lebanon": "lb", "Lesotho": "ls", "Liberia": "lr",
    "Libya": "ly", "Liechtenstein": "li", "Lithuania": "lt", "Luxembourg": "lu", "Madagascar": "mg",
    "Malawi": "mw", "Malaysia": "my", "Maldives": "mv", "Mali": "ml", "Malta": "mt",
    "Marshall Islands": "mh", "Mauritania": "mr", "Mauritius": "mu", "Mexico": "mx", "Micronesia": "fm",
    "Moldova": "md", "Monaco": "mc", "Mongolia": "mn", "Montenegro": "me", "Morocco": "ma",
    "Mozambique": "mz", "Myanmar": "mm", "Namibia": "na", "Nauru": "nr", "Nepal": "np",
    "Netherlands": "nl", "New Zealand": "nz", "Nicaragua": "ni", "Niger": "ne", "Nigeria": "ng",
    "North Korea": "kp", "North Macedonia": "mk", "Norfolk Island": "nf", "Norway": "no", "Oman": "om",
    "Pakistan": "pk", "Palau": "pw", "Palestine": "ps", "Panama": "pa", "Papua New Guinea": "pg",
    "Paraguay": "py", "Peru": "pe", "Philippines": "ph", "Poland": "pl", "Portugal": "pt",
    "Qatar": "qa", "Romania": "ro", "Russia": "ru", "Rwanda": "rw", "Saint Kitts and Nevis": "kn",
    "Saint Lucia": "lc", "Saint Vincent and the Grenadines": "vc", "Samoa": "ws", "San Marino": "sm",
    "Sao Tome and Principe": "st", "Saudi Arabia": "sa", "Senegal": "sn", "Serbia": "rs", "Seychelles": "sc",
    "Sierra Leone": "sl", "Singapore": "sg", "Slovakia": "sk", "Slovenia": "si", "Solomon Islands": "sb",
    "Somalia": "so", "South Africa": "za", "South Korea": "kr", "South Sudan": "ss", "Spain": "es",
    "Sri Lanka": "lk", "Sudan": "sd", "Suriname": "sr", "Sweden": "se", "Switzerland": "ch",
    "Syria": "sy", "Tajikistan": "tj", "Tanzania": "tz", "Thailand": "th", "Timor-Leste": "tl",
    "Togo": "tg", "Tonga": "to", "Trinidad and Tobago": "tt", "Tunisia": "tn", "Turkey": "tr",
    "Turkmenistan": "tm", "Tuvalu": "tv", "Uganda": "ug", "Ukraine": "ua", "United Arab Emirates": "ae",
    "United Kingdom": "gb", "United States": "us", "Uruguay": "uy", "Uzbekistan": "uz", "Vanuatu": "vu",
    "Vatican City": "va", "Venezuela": "ve", "Vietnam": "vn", "Yemen": "ye", "Zambia": "zm",
    "Zimbabwe": "zw", "Antarctica": "aq"
}

US_STATES = {
    "No State": "", "Alabama": "al", "Alaska": "ak", "Arizona": "az", "Arkansas": "ar", "California": "ca",
    "Colorado": "co", "Connecticut": "ct", "Delaware": "de", "Florida": "fl", "Georgia": "ga",
    "Hawaii": "hi", "Idaho": "id", "Illinois": "il", "Indiana": "in", "Iowa": "ia",
    "Kansas": "ks", "Kentucky": "ky", "Louisiana": "la", "Maine": "me", "Maryland": "md",
    "Massachusetts": "ma", "Michigan": "mi", "Minnesota": "mn", "Mississippi": "ms", "Missouri": "mo",
    "Montana": "mt", "Nebraska": "ne", "Nevada": "nv", "New Hampshire": "nh", "New Jersey": "nj",
    "New Mexico": "nm", "New York": "ny", "North Carolina": "nc", "North Dakota": "nd", "Ohio": "oh",
    "Oklahoma": "ok", "Oregon": "or", "Pennsylvania": "pa", "Rhode Island": "ri", "South Carolina": "sc",
    "South Dakota": "sd", "Tennessee": "tn", "Texas": "tx", "Utah": "ut", "Vermont": "vt",
    "Virginia": "va", "Washington": "wa", "West Virginia": "wv", "Wisconsin": "wi", "Wyoming": "wy"
}

THEMES = {
    "dark": ("#111", "#fff"), "light": ("#eee", "#000"), "dracula": ("#282a36", "#f8f8f2"),
    "ocean": ("#002", "#0ff"), "matrix": ("#000", "#209400"), "cyberpunk": ("#0d0d0d", "#fcee0a"),
    "candy": ("#ff80b3", "#4a001f")
}

# --- DB Helpers ---

def get_db():
    if not DB_AVAILABLE:
        return None
    url = os.environ.get("DATABASE_URL")
    if not url:
        return None
    try:
        return psycopg.connect(url)
    except Exception as e:
        print(f"DB Connection failed: {e}")
        return None

def init_db():
    if not DB_AVAILABLE:
        return
    db = get_db()
    if not db:
        return
    try:
        c = db.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS users(
          id SERIAL PRIMARY KEY, username TEXT UNIQUE, password TEXT, nickname TEXT,
          avatar TEXT DEFAULT '', theme TEXT DEFAULT 'matrix', timezone TEXT DEFAULT 'UTC',
          country TEXT DEFAULT 'United States', state TEXT DEFAULT '', is_mod BOOLEAN DEFAULT FALSE
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS messages(
          id SERIAL PRIMARY KEY, user_id INTEGER, content TEXT, created_at TIMESTAMPTZ DEFAULT NOW()
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS friendships(
          user_id INTEGER, friend_id INTEGER, PRIMARY KEY (user_id, friend_id)
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS bans(
          user_id INTEGER PRIMARY KEY, mute_until TIMESTAMPTZ
        )""")
        db.commit()
        print("Database initialized successfully.")
    except Exception as e:
        print(f"DB Init error: {e}")
    finally:
        db.close()

# Пробуем инициализировать БД при старте, но не падаем если не вышло
if DB_AVAILABLE:
    init_db()

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

def get_user_data(user_id):
    """Получает данные пользователя из БД или из демо-памяти"""
    db = get_db()
    if db:
        try:
            c = db.cursor()
            c.execute("SELECT username, nickname, avatar, theme, timezone, country, state, is_mod FROM users WHERE id=%s", (user_id,))
            row = c.fetchone()
            db.close()
            if row:
                return {
                    "id": user_id, "username": row[0], "nickname": row[1], "avatar": row[2],
                    "theme": row[3], "timezone": row[4], "country": row[5], "state": row[6], "is_mod": row[7]
                }
        except Exception as e:
            print(f"Get user error: {e}")
    
    # Fallback to Demo
    return DEMO_USERS.get(user_id)

def is_banned(user_id):
    """Проверяет баны"""
    db = get_db()
    if db:
        try:
            c = db.cursor()
            c.execute("SELECT mute_until FROM bans WHERE user_id=%s", (user_id,))
            row = c.fetchone()
            db.close()
            if row:
                if row[0] is None:
                    return "PERMANENT"
                if row[0] > datetime.now(row[0].tzinfo):
                    return "MUTED"
                # Mute expired, clear it
                get_db().cursor().execute("DELETE FROM bans WHERE user_id=%s", (user_id,))
                get_db().commit()
                return None
        except: pass
    
    # Demo check
    if user_id in DEMO_BANS:
        ban_time = DEMO_BANS[user_id]
        if ban_time is None: return "PERMANENT"
        if ban_time > datetime.now(): return "MUTED"
        del DEMO_BANS[user_id]
    return None

@app.route("/", methods=["GET","POST"])
def login():
    if request.method=="POST":
        u = request.form["username"]
        p = request.form["password"]
        db = get_db()
        if db:
            try:
                c = db.cursor()
                c.execute("SELECT id FROM users WHERE username=%s AND password=%s", (u,p))
                r = c.fetchone()
                db.close()
                if r:
                    session["user_id"] = r[0]
                    return redirect("/chat")
            except: pass
        
        # Demo login
        for uid, data in DEMO_USERS.items():
            if data["username"] == u and data["password"] == p:
                session["user_id"] = uid
                return redirect("/chat")
                
        return "Invalid credentials", 401
    return "<form method=post><input name=username placeholder='Username'><input name=password type=password placeholder='Password'><button>Login</button></form><a href=/register>Register</a>"

@app.route("/register", methods=["GET","POST"])
def register():
    global NEXT_DEMO_ID
    if request.method=="POST":
        username = request.form["username"]
        password = request.form["password"]
        country = request.form.get("country", "United States")
        state = request.form.get("state", "")
        tz = request.form.get("timezone", "UTC")
        
        avatar = ""
        if 'avatar_file' in request.files:
            file = request.files['avatar_file']
            if file and file.filename != '':
                ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else 'png'
                new_filename = f"u{NEXT_DEMO_ID}_{uuid.uuid4().hex[:8]}.{ext}"
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], new_filename)
                try:
                    file.save(filepath)
                    avatar = new_filename
                except Exception as e:
                    print(f"Save error: {e}")

        db = get_db()
        if db:
            try:
                c = db.cursor()
                # Simple check for existence
                c.execute("SELECT 1 FROM users WHERE username=%s", (username,))
                if c.fetchone():
                    db.close()
                    return "Username exists", 400
                
                c.execute("""INSERT INTO users(username, password, nickname, avatar, timezone, country, state) 
                             VALUES(%s,%s,%s,%s,%s,%s,%s)""", 
                          (username, password, username, avatar, tz, country, state))
                db.commit()
                c.execute("SELECT id FROM users WHERE username=%s", (username,))
                uid = c.fetchone()[0]
                db.close()
                session["user_id"] = uid
                return redirect("/")
            except Exception as e:
                print(f"Reg DB error: {e}")
                # Fallback to demo if DB fails during insert
                pass
        
        # Demo Registration
        for u in DEMO_USERS.values():
            if u["username"] == username:
                return "Username exists (Demo)", 400
        
        new_id = NEXT_DEMO_ID
        NEXT_DEMO_ID += 1
        DEMO_USERS[new_id] = {
            "id": new_id, "username": username, "password": password, "nickname": username,
            "avatar": avatar, "theme": "matrix", "timezone": tz, "country": country, "state": state, "is_mod": (username == "Dfghj")
        }
        session["user_id"] = new_id
        return redirect("/")

    # Generate Options
    country_opts = "".join([f'<option value="{c}"{" selected" if c=="United States" else ""}>{c}</option>' for c in sorted(COUNTRIES.keys())])
    tz_opts = "".join([f'<option value="{t}">{t}</option>' for t in TIMEZONES])
    
    return f"""
    <body style="background:#000;color:#0f0;font-family:Courier New">
    <h3>Register</h3>
    <form method=post enctype="multipart/form-data">
      <input name=username placeholder="Username" required><br><br>
      <input name=password type=password placeholder="Password" required><br><br>
      <label>Avatar: <input type=file name=avatar_file accept="image/*"></label><br><br>
      
      <label>Country: 
        <select name=country id="countrySelect" onchange="toggleState()">
          {country_opts}
        </select>
      </label><br><br>
      
      <div id="stateDiv" style="display:none">
        <label>State: 
          <select name=state>
            <option value="">No State</option>
            {"".join([f'<option value="{code}">{name}</option>' for name, code in US_STATES.items()])}
          </select>
        </label><br><br>
      </div>
      
      <label>TZ: <select name=timezone>{tz_opts}</select></label><br><br>
      <button>Register</button>
    </form>
    <script>
      function toggleState() {{
        const sel = document.getElementById('countrySelect');
        const div = document.getElementById('stateDiv');
        div.style.display = (sel.value === 'United States') ? 'block' : 'none';
      }}
      // Init
      toggleState();
    </script>
    </body>
    """

@app.route("/chat")
def chat():
    if "user_id" not in session:
        return redirect("/")
    
    uid = session["user_id"]
    user = get_user_data(uid)
    if not user:
        session.clear()
        return redirect("/")
        
    colors = THEMES.get(user['theme'], THEMES['matrix'])
    
    # Load Messages
    msgs = []
    db = get_db()
    if db:
        try:
            c = db.cursor()
            c.execute("""SELECT m.content, m.created_at, m.user_id 
                         FROM messages m ORDER BY m.created_at ASC LIMIT 100""")
            rows = c.fetchall()
            db.close()
            for row in rows:
                u_data = get_user_data(row[2])
                if u_data:
                    tz = ZoneInfo(u_data['timezone'])
                    local_time = row[1].astimezone(tz).strftime("%H:%M:%S")
                    msgs.append({
                        "text": row[0], "time": local_time, 
                        "nick": u_data['nickname'], "avatar": u_data['avatar'],
                        "country": u_data['country'], "state": u_data['state'],
                        "user_id": u_data['id'], "is_mod": u_data.get('is_mod', False)
                    })
        except Exception as e:
            print(f"Load msgs error: {e}")
    else:
        # Demo msgs
        for m in DEMO_MESSAGES:
            u_data = DEMO_USERS.get(m['user_id'])
            if u_data:
                # Simple time formatting for demo
                t_str = m['time'].strftime("%H:%M:%S") if isinstance(m['time'], datetime) else str(m['time'])
                msgs.append({
                    "text": m['text'], "time": t_str,
                    "nick": u_data['nickname'], "avatar": u_data['avatar'],
                    "country": u_data['country'], "state": u_data['state'],
                    "user_id": u_data['id'], "is_mod": u_data.get('is_mod', False)
                })

    # Render HTML
    msg_html = ""
    for m in msgs:
        flag_main = COUNTRIES.get(m['country'], 'xx')
        flag_state = US_STATES.get(m['state']) if m.get('state') else None
        
        flags_html = f'<img src="https://flagcdn.com/24x18/{flag_main}.png" alt="{m["country"]}">'
        if flag_state:
            flags_html += f'<img src="https://flagcdn.com/24x18/us-{flag_state}.png" alt="{m["state"]}" style="margin-left:2px">'
            
        avatar_src = f"/static/avatars/{m['avatar']}" if m['avatar'] else f"https://flagcdn.com/48x36/{flag_main}.png"
        
        mod_badge = "🛡️" if m.get('is_mod') else ""
        
        msg_html += f"""
        <div style="margin-bottom:10px; border-bottom:1px solid #333; padding:5px;">
          <img src="{avatar_src}" width=32 style="vertical-align:middle; border-radius:4px">
          <b>{mod_badge} {m['nick']}</b> {flags_html}
          <small style="color:#888">{m['time']}</small><br>
          <span style="margin-left:40px">{m['text']}</span>
        </div>
        """

    return f"""
    <!doctype html>
    <body style="margin:0;background:{colors[0]};color:{colors[1]};font-family:Courier New">
    <div style="padding:10px;border-bottom:1px solid {colors[1]}">
      {user['nickname']} | <a href="/settings" style="color:{colors[1]}">Settings</a> | <a href="/logout">Logout</a>
    </div>
    <div id="chat" style="height:75vh;overflow-y:auto;padding:10px">{msg_html}</div>
    <div style="padding:10px;display:flex">
      <input id="msgInput" style="flex:1;padding:10px" placeholder="Type message... (/help for commands)">
      <button onclick="send()" style="padding:10px 20px">Send</button>
    </div>
    <script src="https://cdn.socket.io/4.7.2/socket.io.min.js"></script>
    <script>
      const s = io();
      const chat = document.getElementById('chat');
      const input = document.getElementById('msgInput');
      
      s.on('msg', (m) => {{
        let flags = `<img src="https://flagcdn.com/24x18/${{m.country.toLowerCase()}}.png">`;
        if(m.state) flags += `<img src="https://flagcdn.com/24x18/us-${{m.state}}.png" style="margin-left:2px">`;
        
        let avatar = m.avatar ? `/static/avatars/${{m.avatar}}` : `https://flagcdn.com/48x36/${{m.country.toLowerCase()}}.png`;
        let badge = m.is_mod ? '🛡️' : '';
        
        let html = `
        <div style="margin-bottom:10px; border-bottom:1px solid #333; padding:5px;">
          <img src="${{avatar}}" width=32 style="vertical-align:middle; border-radius:4px">
          <b>${{badge}} ${{m.nick}}</b> ${{flags}}
          <small style="color:#888">${{m.time}}</small><br>
          <span style="margin-left:40px">${{m.text}}</span>
        </div>`;
        chat.innerHTML += html;
        chat.scrollTop = chat.scrollHeight;
      }});

      function send() {{
        const txt = input.value.trim();
        if(txt) {{
          s.emit('msg', txt);
          input.value = '';
        }}
      }}
      input.addEventListener('keypress', e => {{ if(e.key==='Enter') send() }});
    </script>
    </body>
    """

@socketio.on('msg')
def handle_msg(text):
    uid = connected_users.get(request.sid)
    if not uid: return
    
    # Check Ban
    ban_status = is_banned(uid)
    if ban_status == "PERMANENT":
        emit('err', {'msg': 'You are permanently banned.'})
        return
    if ban_status == "MUTED":
        emit('err', {'msg': 'You are temporarily muted.'})
        return

    user = get_user_data(uid)
    if not user: return

    # Commands
    if text.startswith('/'):
        parts = text.split()
        cmd = parts[0].lower()
        
        # Only Dfghj or Mods can use some commands
        is_admin = (user['username'] == 'Dfghj')
        is_mod = user.get('is_mod', False) or is_admin
        
        if cmd == '/help':
            help_text = "Commands: /ban @ID, /mute @ID [hours], /clear (mods), /del @ID (admin)"
            emit('msg', {
                "text": help_text, "time": datetime.now().strftime("%H:%M"),
                "nick": "System", "avatar": "", "country": "United Nations", "state": "",
                "user_id": 0, "is_mod": False
            })
            return

        if cmd == '/clear' and is_mod:
            db = get_db()
            if db:
                try:
                    c = db.cursor()
                    c.execute("DELETE FROM messages")
                    db.commit()
                    db.close()
                except: pass
            else:
                DEMO_MESSAGES.clear()
            emit('sys', {'msg': 'Chat cleared by moderator'})
            # Force reload via custom event or just let them see empty chat next time
            return

        if cmd == '/del' and is_admin:
            if len(parts) < 2: return
            target_id = int(parts[1].replace('@',''))
            db = get_db()
            if db:
                try:
                    c = db.cursor()
                    c.execute("DELETE FROM users WHERE id=%s", (target_id,))
                    c.execute("DELETE FROM messages WHERE user_id=%s", (target_id,))
                    db.commit()
                    db.close()
                except: pass
            else:
                if target_id in DEMO_USERS: del DEMO_USERS[target_id]
            emit('sys', {'msg': f'User {target_id} deleted.'})
            return

        if (cmd == '/ban' or cmd == '/mute') and is_mod:
            if len(parts) < 2: return
            target_id = int(parts[1].replace('@',''))
            
            db = get_db()
            if db:
                try:
                    c = db.cursor()
                    if cmd == '/ban':
                        c.execute("INSERT INTO bans(user_id, mute_until) VALUES(%s, NULL) ON CONFLICT (user_id) DO UPDATE SET mute_until=NULL", (target_id,))
                    else: # mute
                        hours = int(parts[2]) if len(parts)>2 else 1
                        until = datetime.now() + timedelta(hours=hours)
                        c.execute("INSERT INTO bans(user_id, mute_until) VALUES(%s, %s) ON CONFLICT (user_id) DO UPDATE SET mute_until=%s", (target_id, until, until))
                    db.commit()
                    db.close()
                except Exception as e: print(e)
            else:
                if cmd == '/ban':
                    DEMO_BANS[target_id] = None
                else:
                    hours = int(parts[2]) if len(parts)>2 else 1
                    DEMO_BANS[target_id] = datetime.now() + timedelta(hours=hours)
            
            emit('sys', {'msg': f'User {target_id} {"banned" if cmd=="/ban" else "muted"}.'})
            return

    # Normal Message
    now = datetime.now()
    
    db = get_db()
    if db:
        try:
            c = db.cursor()
            c.execute("INSERT INTO messages(user_id, content) VALUES(%s,%s)", (uid, text))
            db.commit()
            db.close()
        except Exception as e:
            print(f"Msg save error: {e}")
            return # Don't broadcast if save failed
    else:
        DEMO_MESSAGES.append({"user_id": uid, "text": text, "time": now})

    # Broadcast
    tz = ZoneInfo(user['timezone'])
    local_time = now.astimezone(tz).strftime("%H:%M:%S")
    
    emit('msg', {
        "text": text, "time": local_time,
        "nick": user['nickname'], "avatar": user['avatar'],
        "country": user['country'], "state": user['state'],
        "user_id": uid, "is_mod": user.get('is_mod', False)
    }, broadcast=True)

@app.route("/settings", methods=["GET","POST"])
def settings():
    if "user_id" not in session: return redirect("/")
    uid = session["user_id"]
    user = get_user_data(uid)
    if not user: return redirect("/")
    
    if request.method == "POST":
        nick = request.form.get("nickname", user['nickname'])
        country = request.form.get("country", user['country'])
        state = request.form.get("state", "")
        tz = request.form.get("timezone", user['timezone'])
        theme = request.form.get("theme", user['theme'])
        
        avatar = user['avatar']
        if 'avatar_file' in request.files:
            file = request.files['avatar_file']
            if file and file.filename != '':
                ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else 'png'
                new_filename = f"u{uid}_{uuid.uuid4().hex[:8]}.{ext}"
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], new_filename)
                try:
                    file.save(filepath)
                    avatar = new_filename
                except: pass

        db = get_db()
        if db:
            try:
                c = db.cursor()
                c.execute("""UPDATE users SET nickname=%s, avatar=%s, theme=%s, timezone=%s, country=%s, state=%s WHERE id=%s""",
                          (nick, avatar, theme, tz, country, state, uid))
                db.commit()
                db.close()
            except: pass
        else:
            DEMO_USERS[uid].update({
                "nickname": nick, "avatar": avatar, "theme": theme, 
                "timezone": tz, "country": country, "state": state
            })
        return redirect("/chat")

    country_opts = "".join([f'<option value="{c}"{" selected" if c==user["country"] else ""}>{c}</option>' for c in sorted(COUNTRIES.keys())])
    tz_opts = "".join([f'<option value="{t}"{" selected" if t==user["timezone"] else ""}>{t}</option>' for t in TIMEZONES])
    theme_opts = "".join([f'<option value="{t}"{" selected" if t==user["theme"] else ""}>{t}</option>' for t in THEMES.keys()])
    
    is_us = user['country'] == 'United States'
    state_opts = "".join([f'<option value="{code}"{" selected" if code==user["state"] else ""}>{name}</option>' for name, code in US_STATES.items()])

    return f"""
    <body style="background:#000;color:#0f0;font-family:Courier New">
    <h3>Settings</h3>
    <form method=post enctype="multipart/form-data">
      Nick: <input name=nickname value="{user['nickname']}"><br><br>
      Avatar: <input type=file name=avatar_file accept="image/*"><br>
      Current: {user['avatar'] if user['avatar'] else 'Default Flag'}<br><br>
      
      Country: <select name=country id="cSelect" onchange="document.getElementById('sDiv').style.display=(this.value==='United States'?'block':'none')">
        {country_opts}
      </select><br><br>
      
      <div id="sDiv" style="display:{'block' if is_us else 'none'}">
        State: <select name=state>{state_opts}</select><br><br>
      </div>
      
      TZ: <select name=timezone>{tz_opts}</select><br><br>
      Theme: <select name=theme>{theme_opts}</select><br><br>
      <button>Save</button>
    </form>
    <a href="/chat">Back</a>
    </body>
    """

@app.route("/static/avatars/<path:filename>")
def serve_avatar(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"Starting server on port {port} (DB Available: {DB_AVAILABLE})")
    socketio.run(app, host="0.0.0.0", port=port, debug=False, allow_unsafe_werkzeug=True)
