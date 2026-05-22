import os
import psycopg
from flask import Flask, request, session, redirect, send_from_directory, jsonify
from flask_socketio import SocketIO, emit, disconnect
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import uuid
import re

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev")
app.config['UPLOAD_FOLDER'] = 'static/avatars'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max

# --- ИСПРАВЛЕНИЕ: Создаем папку для аватарок при старте ---
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])
    print(f"Created directory: {app.config['UPLOAD_FOLDER']}")
# ----------------------------------------------------------

# Важно: manage_session=False для корректной работы сессии Flask
socketio = SocketIO(app, async_mode="threading", manage_session=False)

DATABASE_URL = os.environ.get("DATABASE_URL")

# ---------- DB ----------

def get_db():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set in environment variables")
    conn = psycopg.connect(DATABASE_URL)
    return conn

def init_db():
    db = get_db()
    c = db.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS users(
      id SERIAL PRIMARY KEY,
      username TEXT UNIQUE,
      password TEXT,
      nickname TEXT,
      avatar TEXT, 
      theme TEXT DEFAULT 'matrix',
      timezone_offset INTEGER DEFAULT 0,
      country_code TEXT DEFAULT 'US'
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS messages(
      id SERIAL PRIMARY KEY,
      user_id INTEGER REFERENCES users(id),
      content TEXT,
      created_at TIMESTAMPTZ DEFAULT NOW()
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS friendships(
      user_id INTEGER REFERENCES users(id),
      friend_id INTEGER REFERENCES users(id),
      PRIMARY KEY (user_id, friend_id)
    )
    """)

    # Таблица банов (навсегда)
    c.execute("""
    CREATE TABLE IF NOT EXISTS bans(
      user_id INTEGER PRIMARY KEY REFERENCES users(id),
      banned_by INTEGER REFERENCES users(id),
      reason TEXT,
      created_at TIMESTAMPTZ DEFAULT NOW()
    )
    """)

    # Таблица мутов (временно)
    c.execute("""
    CREATE TABLE IF NOT EXISTS mutes(
      user_id INTEGER PRIMARY KEY REFERENCES users(id),
      muted_by INTEGER REFERENCES users(id),
      until_time TIMESTAMPTZ,
      created_at TIMESTAMPTZ DEFAULT NOW()
    )
    """)

    db.commit()
    db.close()

# Попытка подключения к БД с ретраями (так как Railway PG иногда стартует долго)
if DATABASE_URL:
    retry_count = 0
    while retry_count < 5:
        try:
            init_db()
            print("Database initialized successfully.")
            break
        except Exception as e:
            retry_count += 1
            print(f"DB connection attempt {retry_count} failed: {e}. Retrying in 2s...")
            import time
            time.sleep(2)
    if retry_count == 5:
        print("CRITICAL: Could not initialize database after 5 attempts.")

# ---------- THEMES & COUNTRIES ----------

THEMES = {
    "dark": ("#111", "#fff"),
    "light": ("#eee", "#000"),
    "dracula": ("#282a36", "#f8f8f2"),
    "ocean": ("#002", "#0ff"),
    "crowd_control": ("#1c4975", "#e6f0ff"),
    "aero": ("#80f6ff", "#003b44"),
    "candy": ("#ff80b3", "#4a001f"),
    "matrix": ("#000", "#209400"),
    "contrast_dark": ("#000", "#8400ff"),
    "contrast_light": ("#ffffff", "#cc1616"),
    "theatre": ("#242424", "#b8000c"),
}

# Список стран (код ISO 3166-1 alpha-2 для флагов)
COUNTRIES = [
    ("AF", "Afghanistan"), ("AL", "Albania"), ("DZ", "Algeria"), ("AD", "Andorra"), ("AO", "Angola"),
    ("AG", "Antigua and Barbuda"), ("AR", "Argentina"), ("AM", "Armenia"), ("AU", "Australia"), ("AT", "Austria"),
    ("AZ", "Azerbaijan"), ("BS", "Bahamas"), ("BH", "Bahrain"), ("BD", "Bangladesh"), ("BB", "Barbados"),
    ("BY", "Belarus"), ("BE", "Belgium"), ("BZ", "Belize"), ("BJ", "Benin"), ("BT", "Bhutan"),
    ("BO", "Bolivia"), ("BA", "Bosnia and Herzegovina"), ("BW", "Botswana"), ("BR", "Brazil"), ("BN", "Brunei"),
    ("BG", "Bulgaria"), ("BF", "Burkina Faso"), ("BI", "Burundi"), ("CV", "Cabo Verde"), ("KH", "Cambodia"),
    ("CM", "Cameroon"), ("CA", "Canada"), ("CF", "Central African Republic"), ("TD", "Chad"), ("CL", "Chile"),
    ("CN", "China"), ("CO", "Colombia"), ("KM", "Comoros"), ("CG", "Congo (Brazzaville)"), ("CD", "Congo (Kinshasa)"),
    ("CR", "Costa Rica"), ("HR", "Croatia"), ("CU", "Cuba"), ("CY", "Cyprus"), ("CZ", "Czechia"),
    ("DK", "Denmark"), ("DJ", "Djibouti"), ("DM", "Dominica"), ("DO", "Dominican Republic"), ("EC", "Ecuador"),
    ("EG", "Egypt"), ("SV", "El Salvador"), ("GQ", "Equatorial Guinea"), ("ER", "Eritrea"), ("EE", "Estonia"),
    ("SZ", "Eswatini"), ("ET", "Ethiopia"), ("FJ", "Fiji"), ("FI", "Finland"), ("FR", "France"),
    ("GA", "Gabon"), ("GM", "Gambia"), ("GE", "Georgia"), ("DE", "Germany"), ("GH", "Ghana"),
    ("GR", "Greece"), ("GD", "Grenada"), ("GT", "Guatemala"), ("GN", "Guinea"), ("GW", "Guinea-Bissau"),
    ("GY", "Guyana"), ("HT", "Haiti"), ("HN", "Honduras"), ("HU", "Hungary"), ("IS", "Iceland"),
    ("IN", "India"), ("ID", "Indonesia"), ("IR", "Iran"), ("IQ", "Iraq"), ("IE", "Ireland"),
    ("IL", "Israel"), ("IT", "Italy"), ("JM", "Jamaica"), ("JP", "Japan"), ("JO", "Jordan"),
    ("KZ", "Kazakhstan"), ("KE", "Kenya"), ("KI", "Kiribati"), ("KW", "Kuwait"), ("KG", "Kyrgyzstan"),
    ("LA", "Laos"), ("LV", "Latvia"), ("LB", "Lebanon"), ("LS", "Lesotho"), ("LR", "Liberia"),
    ("LY", "Libya"), ("LI", "Liechtenstein"), ("LT", "Lithuania"), ("LU", "Luxembourg"), ("MG", "Madagascar"),
    ("MW", "Malawi"), ("MY", "Malaysia"), ("MV", "Maldives"), ("ML", "Mali"), ("MT", "Malta"),
    ("MH", "Marshall Islands"), ("MR", "Mauritania"), ("MU", "Mauritius"), ("MX", "Mexico"), ("FM", "Micronesia"),
    ("MD", "Moldova"), ("MC", "Monaco"), ("MN", "Mongolia"), ("ME", "Montenegro"), ("MA", "Morocco"),
    ("MZ", "Mozambique"), ("MM", "Myanmar"), ("NA", "Namibia"), ("NR", "Nauru"), ("NP", "Nepal"),
    ("NL", "Netherlands"), ("NZ", "New Zealand"), ("NI", "Nicaragua"), ("NE", "Niger"), ("NG", "Nigeria"),
    ("KP", "North Korea"), ("MK", "North Macedonia"), ("NF", "Norfolk Island"), ("NO", "Norway"), ("OM", "Oman"),
    ("PK", "Pakistan"), ("PW", "Palau"), ("PS", "Palestine"), ("PA", "Panama"), ("PG", "Papua New Guinea"),
    ("PY", "Paraguay"), ("PE", "Peru"), ("PH", "Philippines"), ("PL", "Poland"), ("PT", "Portugal"),
    ("QA", "Qatar"), ("RO", "Romania"), ("RU", "Russia"), ("RW", "Rwanda"), ("KN", "Saint Kitts and Nevis"),
    ("LC", "Saint Lucia"), ("VC", "Saint Vincent and the Grenadines"), ("WS", "Samoa"), ("SM", "San Marino"),
    ("ST", "Sao Tome and Principe"), ("SA", "Saudi Arabia"), ("SN", "Senegal"), ("RS", "Serbia"), ("SC", "Seychelles"),
    ("SL", "Sierra Leone"), ("SG", "Singapore"), ("SK", "Slovakia"), ("SI", "Slovenia"), ("SB", "Solomon Islands"),
    ("SO", "Somalia"), ("ZA", "South Africa"), ("KR", "South Korea"), ("SS", "South Sudan"), ("ES", "Spain"),
    ("LK", "Sri Lanka"), ("SD", "Sudan"), ("SR", "Suriname"), ("SE", "Sweden"), ("CH", "Switzerland"),
    ("SY", "Syria"), ("TJ", "Tajikistan"), ("TZ", "Tanzania"), ("TH", "Thailand"), ("TL", "Timor-Leste"),
    ("TG", "Togo"), ("TO", "Tonga"), ("TT", "Trinidad and Tobago"), ("TN", "Tunisia"), ("TR", "Turkey"),
    ("TM", "Turkmenistan"), ("TV", "Tuvalu"), ("UG", "Uganda"), ("UA", "Ukraine"), ("AE", "United Arab Emirates"),
    ("GB", "United Kingdom"), ("US", "United States"), ("UY", "Uruguay"), ("UZ", "Uzbekistan"), ("VU", "Vanuatu"),
    ("VA", "Vatican City"), ("VE", "Venezuela"), ("VN", "Vietnam"), ("YE", "Yemen"), ("ZM", "Zambia"),
    ("ZW", "Zimbabwe"), ("AQ", "Antarctica")
]

# Часовые пояса от -12 до +14
TIMEZONES = [f"UTC{offset}" for offset in range(-12, 15)]

# ID администратора (Dfghj) и модераторов
ADMIN_USERNAME = "Dfghj"
# Можно добавить ID других модераторов сюда, если нужно
MODERATOR_IDS = [] 

# ---------- AUTH ----------

@app.route("/", methods=["GET","POST"])
def login():
    if request.method=="POST":
        u = request.form["username"]
        p = request.form["password"]

        db=get_db(); c=db.cursor()
        c.execute("SELECT id FROM users WHERE username=%s AND password=%s",(u,p))
        r=c.fetchone()
        if r:
            session["user_id"]=r[0]
            db.close()
            return redirect("/chat")
        db.close()
    return "<form method=post><input name=username><input name=password type=password><button>Login</button></form><a href=/register>Register</a>"

@app.route("/register", methods=["GET","POST"])
def register():
    if request.method=="POST":
        db=get_db(); c=db.cursor()
        try:
            c.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM users")
            new_id = c.fetchone()[0]
            
            avatar = None # Теперь аватарка опциональна, по умолчанию нет картинки
            country_code = request.form.get("country", "US")
            
            if 'avatar_file' in request.files:
                file = request.files['avatar_file']
                if file and file.filename != '':
                    ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else 'png'
                    new_filename = f"u{new_id}_{uuid.uuid4().hex[:8]}.{ext}"
                    filepath = os.path.join(app.config['UPLOAD_FOLDER'], new_filename)
                    file.save(filepath)
                    avatar = new_filename
            
            c.execute(
              "INSERT INTO users(id, username, password, avatar, nickname, country_code, timezone_offset) VALUES(%s,%s,%s,%s,%s,%s,%s)",
              (
                new_id,
                request.form["username"],
                request.form["password"],
                avatar,
                request.form["username"],
                country_code,
                int(request.form.get("timezone_offset", 0))
              )
            )
            db.commit()
        except psycopg.IntegrityError:
             db.close()
             return "Username already exists!", 400
        db.close()
        return redirect("/")
    
    country_options = "".join([f'<option value="{code}">{name}</option>' for code, name in COUNTRIES])
    tz_options = "".join([f'<option value="{tz}">{tz}</option>' for tz in TIMEZONES])
    
    return f"""
    <body style="background:#000;color:#0f0;font-family:Courier New">
    <h3>Register</h3>
    <form method=post enctype="multipart/form-data">
      <input name=username placeholder=username><br>
      <input name=password type=password placeholder=password><br>
      <label>Upload Avatar (optional): <input type=file name=avatar_file accept="image/*"></label><br>
      Country:<select name=country>{country_options}</select><br>
      Timezone:<select name=timezone_offset>{tz_options}</select><br>
      <button>Register</button>
    </form>
    </body>
    """

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# --- Сохранение сессии пользователя для сокета ---
connected_users = {}

@socketio.on('connect')
def handle_connect():
    user_id = session.get('user_id')
    if user_id is None:
        print(f"Socket connection rejected: No user_id in session for SID {request.sid}")
        disconnect()
        return False
    else:
        connected_users[request.sid] = user_id
        print(f"User {user_id} connected with SID {request.sid}")

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    if sid in connected_users:
        user_id = connected_users.pop(sid)
        print(f"User {user_id} disconnected, SID {sid}")

# ---------- CHAT ----------

@app.route("/chat")
def chat():
    if "user_id" not in session:
        return redirect("/")

    db=get_db(); c=db.cursor()
    c.execute("SELECT nickname,avatar,theme,timezone_offset,country_code FROM users WHERE id=%s",(session["user_id"],))
    nick,avatar,theme,tz_offset,country_code=c.fetchone()
    colors=THEMES.get(theme,THEMES["matrix"])
    
    # Получаем список ID друзей
    c.execute("SELECT friend_id FROM friendships WHERE user_id=%s", (session["user_id"],))
    friend_ids = [row[0] for row in c.fetchall()]
    
    # Получаем историю сообщений
    c.execute("""
        SELECT m.content, m.created_at, u.nickname, u.avatar, u.timezone_offset, u.id, u.country_code
        FROM messages m
        JOIN users u ON m.user_id = u.id
        ORDER BY m.created_at ASC
        LIMIT 100
    """)
    messages = []
    for row in c.fetchall():
        content, created_at, msg_nick, msg_avatar, msg_tz_off, msg_user_id, msg_country = row
        
        # Расчет времени с учетом смещения UTC
        utc_time = created_at.replace(tzinfo=ZoneInfo("UTC"))
        # Создаем фиктивный таймзону для смещения, так как ZoneInfo требует имя, а у нас оффсет
        # Проще: добавляем дельту к UTC времени
        local_time_obj = utc_time + timedelta(hours=msg_tz_off)
        local_time = local_time_obj.strftime("%H:%M:%S")
        
        messages.append({
            "text": content,
            "time": local_time,
            "nick": msg_nick,
            "avatar": msg_avatar,
            "country": msg_country,
            "user_id": msg_user_id
        })
    
    db.close()

    messages_html = ""
    for m in messages:
        is_friend = m["user_id"] in friend_ids
        style = 'border: 2px solid #0f0; background: rgba(0, 255, 0, 0.1); padding: 5px;' if is_friend else ''
        
        # Флаг картинкой
        flag_img = f'<img src="https://flagcdn.com/16x12/{m["country"].lower()}.png" alt="{m["country"]}" style="vertical-align:middle;margin:0 4px;">'
        
        # Аватарка (если есть)
        avatar_img = f'<img src="/static/avatars/{m["avatar"]}" width=32 style="vertical-align:middle;margin-right:5px;border-radius:50%;">' if m["avatar"] else '<span style="display:inline-block;width:32px;height:32px;background:#333;border-radius:50%;margin-right:5px;"></span>'
        
        nick_link = f'<a href="/profile/{m["user_id"]}" style="color: inherit; text-decoration: none;">{m["nick"]}</a>'
        
        messages_html += f'''
        <div style="{style}; margin-bottom: 8px; display:flex; align-items:flex-start;">
          {avatar_img}
          <div>
            <b>{nick_link}</b> {flag_img} <small>(ID: {m["user_id"]})</small>
            <small style="color:#888">{m["time"]}</small><br>
            <span style="word-wrap:break-word;">{m["text"]}</span>
          </div>
        </div>'''

    return f"""
<!doctype html>
<body style="margin:0;background:{colors[0]};color:{colors[1]};font-family:Courier New">
<div style="padding:10px;border-bottom:1px solid {colors[1]}">
  {nick} (ID: {session['user_id']})
  <a href=/settings>Settings</a>
  <a href=/leaderboard>Leaderboard</a>
  <a href=/logout>Logout</a>
</div>

<div id=chat style="height:70vh;overflow:auto;padding:10px">{messages_html}</div>

<div style="display:flex">
  <input id=msg style="flex:1" placeholder="Type message or /command..." onkeydown="if(event.key==='Enter')send()">
  <button onclick=send()>Send</button>
</div>

<script src="https://cdn.socket.io/4.7.2/socket.io.min.js"></script>
<script>
let s=io();
const friendIds = {friend_ids};

s.on("connect", () => {{
    console.log("Connected to server via Socket.IO");
}});

s.on("msg", m => {{
    appendMessage(m);
}});

s.on("clear_chat", () => {{
    document.getElementById('chat').innerHTML = '';
}});

function appendMessage(m) {{
    const isFriend = friendIds.includes(m.user_id);
    const style = isFriend ? 'border: 2px solid #0f0; background: rgba(0, 255, 0, 0.1); padding: 5px;' : '';
    const nickLink = `<a href="/profile/${{m.user_id}}" style="color: inherit; text-decoration: none;">${{m.nick}}</a>`;
    
    const avatarHtml = m.avatar ? `<img src="/static/avatars/${{m.avatar}}" width=32 style="vertical-align:middle;margin-right:5px;border-radius:50%;">` : '<span style="display:inline-block;width:32px;height:32px;background:#333;border-radius:50%;margin-right:5px;"></span>';
    const flagImg = `<img src="https://flagcdn.com/16x12/${{m.country.toLowerCase()}}.png" alt="${{m.country}}" style="vertical-align:middle;margin:0 4px;">`;

    const html = `
    <div style="${{style}}; margin-bottom: 8px; display:flex; align-items:flex-start;">
      ${{avatarHtml}}
      <div>
        <b>${{nickLink}}</b> ${{flagImg}} <small>(ID: ${{m.user_id}})</small>
        <small style="color:#888">${{m.time}}</small><br>
        <span style="word-wrap:break-word;">${{m.text}}</span>
      </div>
    </div>`;
    
    const chat = document.getElementById('chat');
    chat.innerHTML += html;
    chat.scrollTop = chat.scrollHeight;
}}

function send(){{
  const input = document.getElementById('msg');
  const text = input.value.trim();
  if (text) {{
    s.emit("msg", text);
    input.value="";
  }}
}}
</script>
</body>
"""

# ---------- SOCKET (обработка сообщений и команд) ----------

@socketio.on("msg")
def msg(text):
    user_id = connected_users.get(request.sid)
    if user_id is None:
        return

    db = None
    try:
        db = get_db()
        c = db.cursor()
        
        # Получаем данные пользователя
        c.execute("""
          SELECT username, nickname, avatar, timezone_offset, country_code
          FROM users WHERE id=%s
        """, (user_id,))
        user_data = c.fetchone()
        if not user_data:
            return
        username, nick, avatar, tz_offset, country_code = user_data

        # Проверка на бан
        c.execute("SELECT 1 FROM bans WHERE user_id=%s", (user_id,))
        if c.fetchone():
            emit("error", {"message": "You are banned!"})
            return

        # Проверка на мут
        c.execute("SELECT until_time FROM mutes WHERE user_id=%s", (user_id,))
        mute_row = c.fetchone()
        if mute_row:
            until_time = mute_row[0]
            if datetime.now(ZoneInfo("UTC")) < until_time:
                emit("error", {"message": f"You are muted until {until_time}!"})
                return
            else:
                # Мут истек, удаляем запись
                c.execute("DELETE FROM mutes WHERE user_id=%s", (user_id,))
                db.commit()

        # Обработка команд модератора
        if text.startswith("/"):
            parts = text.split()
            cmd = parts[0].lower()
            
            # Проверка прав модератора (ID из списка или юзернейм Dfghj)
            is_admin = (username == ADMIN_USERNAME)
            is_mod = (user_id in MODERATOR_IDS) or is_admin
            
            if cmd == "/clear":
                if is_mod:
                    c.execute("DELETE FROM messages")
                    db.commit()
                    emit("clear_chat", broadcast=True)
                    emit("sys_msg", {"text": "Chat cleared by moderator."}, broadcast=True)
                else:
                    emit("error", {"message": "Permission denied."})
                return

            if cmd == "/del":
                if is_admin:
                    if len(parts) < 2:
                        emit("error", {"message": "Usage: /del @ID"})
                        return
                    target_id_str = parts[1].replace("@", "")
                    try:
                        target_id = int(target_id_str)
                        # Удаляем сообщения
                        c.execute("DELETE FROM messages WHERE user_id=%s", (target_id,))
                        # Удаляем дружбу
                        c.execute("DELETE FROM friendships WHERE user_id=%s OR friend_id=%s", (target_id, target_id))
                        # Удаляем баны/муты
                        c.execute("DELETE FROM bans WHERE user_id=%s", (target_id,))
                        c.execute("DELETE FROM mutes WHERE user_id=%s", (target_id,))
                        # Удаляем юзера
                        c.execute("DELETE FROM users WHERE id=%s", (target_id,))
                        db.commit()
                        emit("sys_msg", {"text": f"User {target_id} deleted by Admin."}, broadcast=True)
                    except ValueError:
                        emit("error", {"message": "Invalid ID format."})
                else:
                    emit("error", {"message": "Only Dfghj can use this command."})
                return

            if cmd == "/ban":
                if is_mod:
                    if len(parts) < 2:
                        emit("error", {"message": "Usage: /ban @ID"})
                        return
                    target_id_str = parts[1].replace("@", "")
                    try:
                        target_id = int(target_id_str)
                        c.execute("INSERT INTO bans(user_id, banned_by, reason) VALUES(%s,%s,%s) ON CONFLICT(user_id) DO NOTHING", 
                                  (target_id, user_id, "Banned by moderator"))
                        db.commit()
                        emit("sys_msg", {"text": f"User {target_id} has been banned."}, broadcast=True)
                    except ValueError:
                        emit("error", {"message": "Invalid ID format."})
                else:
                    emit("error", {"message": "Permission denied."})
                return

            if cmd == "/mute":
                if is_mod:
                    if len(parts) < 3:
                        emit("error", {"message": "Usage: /mute @ID hours"})
                        return
                    target_id_str = parts[1].replace("@", "")
                    try:
                        target_id = int(target_id_str)
                        hours = int(parts[2])
                        until = datetime.now(ZoneInfo("UTC")) + timedelta(hours=hours)
                        c.execute("""
                            INSERT INTO mutes(user_id, muted_by, until_time) 
                            VALUES(%s,%s,%s) 
                            ON CONFLICT(user_id) DO UPDATE SET until_time=%s, muted_by=%s
                        """, (target_id, user_id, until, until, user_id))
                        db.commit()
                        emit("sys_msg", {"text": f"User {target_id} has been muted for {hours} hours."}, broadcast=True)
                    except ValueError:
                        emit("error", {"message": "Invalid ID or hours format."})
                else:
                    emit("error", {"message": "Permission denied."})
                return
            
            # Если команда не распознана, но начинается с /, можно либо игнорировать, либо писать как текст
            # Сейчас просто пропускаем, чтобы не спамить ошибкой, если пользователь просто написал слэш

        # Обычное сообщение
        c.execute("INSERT INTO messages(user_id,content) VALUES(%s,%s)", (user_id, text))
        db.commit()

        # Расчет времени
        utc_now = datetime.now(ZoneInfo("UTC"))
        local_time_obj = utc_now + timedelta(hours=tz_offset)
        local_time = local_time_obj.strftime("%H:%M:%S")

        emit("msg",{
          "nick": nick,
          "avatar": avatar,
          "country": country_code,
          "text": text,
          "time": local_time,
          "user_id": user_id
        }, broadcast=True)

    except Exception as e:
        print(f"Error processing message: {e}")
        if db: db.rollback()
    finally:
        if db: db.close()

# ---------- PROFILE ----------

@app.route("/profile/<int:user_id>")
def profile(user_id):
    if "user_id" not in session:
        return redirect("/")
    
    current_user_id = session["user_id"]
    db = get_db()
    c = db.cursor()
    
    c.execute("SELECT id, username, nickname, avatar, theme, country_code FROM users WHERE id=%s", (user_id,))
    user = c.fetchone()
    if not user:
        db.close()
        return "User not found", 404
    
    u_id, u_username, u_nickname, u_avatar, u_theme, u_country = user
    colors = THEMES.get(u_theme, THEMES["matrix"])
    
    c.execute("SELECT COUNT(*) FROM messages WHERE user_id=%s", (user_id,))
    msg_count = c.fetchone()[0]
    
    c.execute("""
      SELECT u.id, u.username, u.nickname, u.avatar 
      FROM friendships f 
      JOIN users u ON f.friend_id = u.id 
      WHERE f.user_id = %s
    """, (user_id,))
    friends = c.fetchall()
    
    is_friend = False
    if current_user_id != user_id:
        c.execute("SELECT 1 FROM friendships WHERE user_id=%s AND friend_id=%s", (current_user_id, user_id))
        if c.fetchone():
            is_friend = True
    
    db.close()
    
    friends_html = ""
    for f_id, f_user, f_nick, f_av in friends:
        friends_html += f'<a href="/profile/{f_id}"><img src="/static/avatars/{f_av}" width=40 style="border-radius:50%"></a> '
    
    action_button = ""
    if current_user_id != user_id:
        if is_friend:
            action_button = f'<a href="/remove_friend/{user_id}" style="color:red">Remove Friend</a>'
        else:
            action_button = f'<a href="/add_friend/{user_id}" style="color:#0f0">Add Friend</a>'

    flag_img = f'<img src="https://flagcdn.com/48x36/{u_country.lower()}.png" alt="{u_country}" style="vertical-align:middle;margin:10px;">'

    return f"""
    <body style="margin:0;background:{colors[0]};color:{colors[1]};font-family:Courier New">
    <div style="padding:20px">
      <a href="/chat">Back to Chat</a>
      <hr>
      <center>
        {flag_img}<br>
        {f'<img src="/static/avatars/{u_avatar}" width=100 style="border-radius:50%; border: 4px solid {colors[1]}">' if u_avatar else '<div style="width:100px;height:100px;background:#333;border-radius:50%;border:4px solid white;margin:0 auto;"></div>'}
        <h2>{u_nickname}</h2>
        <p>@{u_username} (ID: {u_id})</p>
        <p>Messages: {msg_count}</p>
        <div style="margin: 20px 0;">
          {action_button}
        </div>
        <h3>Friends ({len(friends)})</h3>
        <div>{friends_html if friends_html else "No friends yet"}</div>
      </center>
    </div>
    </body>
    """

@app.route("/add_friend/<int:friend_id>")
def add_friend(friend_id):
    if "user_id" not in session: return redirect("/")
    user_id = session["user_id"]
    if user_id == friend_id: return "Cannot add yourself", 400
    db = get_db(); c = db.cursor()
    try:
        c.execute("INSERT INTO friendships(user_id, friend_id) VALUES(%s, %s)", (user_id, friend_id))
        db.commit()
    except psycopg.IntegrityError: pass
    finally: db.close()
    return redirect(f"/profile/{friend_id}")

@app.route("/remove_friend/<int:friend_id>")
def remove_friend(friend_id):
    if "user_id" not in session: return redirect("/")
    user_id = session["user_id"]
    db = get_db(); c = db.cursor()
    c.execute("DELETE FROM friendships WHERE user_id=%s AND friend_id=%s", (user_id, friend_id))
    db.commit(); db.close()
    return redirect(f"/profile/{friend_id}")

# ---------- SETTINGS ----------

@app.route("/settings", methods=["GET","POST"])
def settings():
    if "user_id" not in session: return redirect("/")
    
    db=get_db(); c=db.cursor()
    if request.method=="POST":
        avatar = request.form.get("avatar", "") # Оставляем старую если файл не загружен
        country_code = request.form.get("country", "US")
        tz_str = request.form.get("timezone_offset", "0")
        # Парсим UTC+X в число
        try:
            tz_offset = int(tz_str.replace("UTC", ""))
        except:
            tz_offset = 0
        
        if 'avatar_file' in request.files:
            file = request.files['avatar_file']
            if file and file.filename != '':
                # Удаляем старый аватар если он был кастомным (не None)
                # (упрощено: просто перезаписываем новым именем, старый остается мусором, можно добавить очистку)
                ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else 'png'
                new_filename = f"u{session['user_id']}_{uuid.uuid4().hex[:8]}.{ext}"
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], new_filename)
                file.save(filepath)
                avatar = new_filename
        elif request.form.get("remove_avatar") == "on":
            avatar = None

        c.execute("""
        UPDATE users SET nickname=%s,avatar=%s,theme=%s,timezone_offset=%s,country_code=%s
        WHERE id=%s
        """, (
          request.form["nickname"],
          avatar,
          request.form["theme"],
          tz_offset,
          country_code,
          session["user_id"]
        ))
        db.commit()
        db.close()
        return redirect("/chat")

    c.execute("SELECT nickname,avatar,theme,timezone_offset,country_code FROM users WHERE id=%s",(session["user_id"],))
    u=c.fetchone()
    db.close()
    
    theme_options = "".join([f'<option value="{t}"{" selected" if t == u[2] else ""}>{t.title()}</option>' for t in THEMES.keys()])
    tz_options = "".join([f'<option value="UTC{off}"{" selected" if off == u[3] else ""}>UTC{off:+d}</option>' for off in range(-12, 15)])
    country_options = "".join([f'<option value="{code}"{" selected" if code == u[4] else ""}>{name}</option>' for code, name in COUNTRIES])

    avatar_preview = ""
    if u[1]:
        avatar_preview = f'<img src="/static/avatars/{u[1]}" width=50><br><label><input type=checkbox name=remove_avatar> Remove current avatar</label><br>'
    else:
        avatar_preview = "No avatar<br>"

    return f"""
    <body style="background:#000;color:#0f0;font-family:Courier New">
    <h3>Settings</h3>
    <form method=post enctype="multipart/form-data">
      Nick:<input name=nickname value="{u[0]}"><br>
      Upload Avatar: <input type=file name=avatar_file accept="image/*"><br>
      {avatar_preview}
      Country:<select name=country>{country_options}</select><br>
      Timezone:<select name=timezone_offset>{tz_options}</select><br>
      Theme:<select name=theme>{theme_options}</select><br>
      <button>Save</button>
    </form>
    </body>
    """

@app.route("/static/avatars/<path:filename>")
def serve_avatar(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# ---------- LEADERBOARD ----------

@app.route("/leaderboard")
def leaderboard():
    db=get_db(); c=db.cursor()
    c.execute("""
    SELECT u.username, COUNT(m.id) as msg_count
    FROM users u LEFT JOIN messages m ON u.id=m.user_id
    GROUP BY u.id ORDER BY msg_count DESC
    """)
    rows=c.fetchall()
    db.close()
    out="<body style='background:#000;color:#0f0;font-family:Courier New'><h3>Leaderboard</h3>"
    for u, cnt in rows:
        out+=f"{u}: {cnt}<br>"
    return out+"<a href=/chat>back</a></body>"

# ---------- RUN ----------

if __name__=="__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"Starting server on port {port}")
    socketio.run(app, host="0.0.0.0", port=port, debug=False, allow_unsafe_werkzeug=True)
