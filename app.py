import os
import time
import psycopg
from flask import Flask, request, session, redirect, send_from_directory
from flask_socketio import SocketIO, emit, disconnect
from datetime import datetime
from zoneinfo import ZoneInfo, available_timezones
import uuid

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

# ---------- СПИСОК СТРАН И ФЛАГОВ ----------

COUNTRIES_LIST = [
    "Afghanistan", "Albania", "Algeria", "Andorra", "Angola", "Antigua and Barbuda",
    "Argentina", "Armenia", "Australia", "Austria", "Azerbaijan", "Bahamas", "Bahrain",
    "Bangladesh", "Barbados", "Belarus", "Belgium", "Belize", "Benin", "Bhutan",
    "Bolivia", "Bosnia and Herzegovina", "Botswana", "Brazil", "Brunei", "Bulgaria",
    "Burkina Faso", "Burundi", "Cabo Verde", "Cambodia", "Cameroon", "Canada",
    "Central African Republic", "Chad", "Chile", "China", "Colombia", "Comoros",
    "Congo (Brazzaville)", "Congo (Kinshasa)", "Costa Rica", "Croatia", "Cuba",
    "Cyprus", "Czechia", "Denmark", "Djibouti", "Dominica", "Dominican Republic",
    "Ecuador", "Egypt", "El Salvador", "Equatorial Guinea", "Eritrea", "Estonia",
    "Eswatini", "Ethiopia", "Fiji", "Finland", "France", "Gabon", "Gambia",
    "Georgia", "Germany", "Ghana", "Greece", "Grenada", "Guatemala", "Guinea",
    "Guinea-Bissau", "Guyana", "Haiti", "Honduras", "Hungary", "Iceland", "India",
    "Indonesia", "Iran", "Iraq", "Ireland", "Israel", "Italy", "Jamaica", "Japan",
    "Jordan", "Kazakhstan", "Kenya", "Kiribati", "Kuwait", "Kyrgyzstan", "Laos",
    "Latvia", "Lebanon", "Lesotho", "Liberia", "Libya", "Liechtenstein", "Lithuania",
    "Luxembourg", "Madagascar", "Malawi", "Malaysia", "Maldives", "Mali", "Malta",
    "Marshall Islands", "Mauritania", "Mauritius", "Mexico", "Micronesia", "Moldova",
    "Monaco", "Mongolia", "Montenegro", "Morocco", "Mozambique", "Myanmar", "Namibia",
    "Nauru", "Nepal", "Netherlands", "New Zealand", "Nicaragua", "Niger", "Nigeria",
    "North Korea", "North Macedonia", "Norfolk Island", "Norway", "Oman", "Pakistan",
    "Palau", "Palestine", "Panama", "Papua New Guinea", "Paraguay", "Peru",
    "Philippines", "Poland", "Portugal", "Qatar", "Romania", "Russia", "Rwanda",
    "Saint Kitts and Nevis", "Saint Lucia", "Saint Vincent and the Grenadines",
    "Samoa", "San Marino", "Sao Tome and Principe", "Saudi Arabia", "Senegal",
    "Serbia", "Seychelles", "Sierra Leone", "Singapore", "Slovakia", "Slovenia",
    "Solomon Islands", "Somalia", "South Africa", "South Korea", "South Sudan",
    "Spain", "Sri Lanka", "Sudan", "Suriname", "Sweden", "Switzerland", "Syria",
    "Tajikistan", "Tanzania", "Thailand", "Timor-Leste", "Togo", "Tonga",
    "Trinidad and Tobago", "Tunisia", "Turkey", "Turkmenistan", "Tuvalu", "Uganda",
    "Ukraine", "United Arab Emirates", "United Kingdom", "United States", "Uruguay",
    "Uzbekistan", "Vanuatu", "Vatican City", "Venezuela", "Vietnam", "Yemen",
    "Zambia", "Zimbabwe", "Antarctica"
]

# Простой маппинг стран на флаги (эмодзи). 
# Для краткости кода используем библиотеку flagemoji или простой словарь, если библиотека не установлена.
# Здесь реализован ручной словарь для надежности без лишних зависимостей.
COUNTRY_FLAGS = {
    "Afghanistan": "🇦🇫", "Albania": "🇦🇱", "Algeria": "🇩🇿", "Andorra": "🇦🇩", "Angola": "🇦🇴",
    "Antigua and Barbuda": "🇦🇬", "Argentina": "🇦🇷", "Armenia": "🇦🇲", "Australia": "🇦🇺",
    "Austria": "🇦🇹", "Azerbaijan": "🇦🇿", "Bahamas": "🇧🇸", "Bahrain": "🇧🇭", "Bangladesh": "🇧🇩",
    "Barbados": "🇧🇧", "Belarus": "🇧🇾", "Belgium": "🇧🇪", "Belize": "🇧🇿", "Benin": "🇧🇯",
    "Bhutan": "🇧🇹", "Bolivia": "🇧🇴", "Bosnia and Herzegovina": "🇧🇦", "Botswana": "🇧🇼",
    "Brazil": "🇧🇷", "Brunei": "🇧🇳", "Bulgaria": "🇧🇬", "Burkina Faso": "🇧🇫", "Burundi": "🇧🇮",
    "Cabo Verde": "🇨🇻", "Cambodia": "🇰🇭", "Cameroon": "🇨🇲", "Canada": "🇨🇦",
    "Central African Republic": "🇨🇫", "Chad": "🇹🇩", "Chile": "🇨🇱", "China": "🇨🇳",
    "Colombia": "🇨🇴", "Comoros": "🇰🇲", "Congo (Brazzaville)": "🇨🇬", "Congo (Kinshasa)": "🇨🇩",
    "Costa Rica": "🇨🇷", "Croatia": "🇭🇷", "Cuba": "🇨🇺", "Cyprus": "🇨🇾", "Czechia": "🇨🇿",
    "Denmark": "🇩🇰", "Djibouti": "🇩🇯", "Dominica": "🇩🇲", "Dominican Republic": "🇩🇴",
    "Ecuador": "🇪🇨", "Egypt": "🇪🇬", "El Salvador": "🇸🇻", "Equatorial Guinea": "🇬🇶",
    "Eritrea": "🇪🇷", "Estonia": "🇪🇪", "Eswatini": "🇸🇿", "Ethiopia": "🇪🇹", "Fiji": "🇫🇯",
    "Finland": "🇫🇮", "France": "🇫🇷", "Gabon": "🇬🇦", "Gambia": "🇬🇲", "Georgia": "🇬🇪",
    "Germany": "🇩🇪", "Ghana": "🇬🇭", "Greece": "🇬🇷", "Grenada": "🇬🇩", "Guatemala": "🇬🇹",
    "Guinea": "🇬🇳", "Guinea-Bissau": "🇬🇼", "Guyana": "🇬🇾", "Haiti": "🇭🇹", "Honduras": "🇭🇳",
    "Hungary": "🇭🇺", "Iceland": "🇮🇸", "India": "🇮🇳", "Indonesia": "🇮🇩", "Iran": "🇮🇷",
    "Iraq": "🇮🇶", "Ireland": "🇮🇪", "Israel": "🇮🇱", "Italy": "🇮🇹", "Jamaica": "🇯🇲",
    "Japan": "🇯🇵", "Jordan": "🇯🇴", "Kazakhstan": "🇰🇿", "Kenya": "🇰🇪", "Kiribati": "🇰🇮",
    "Kuwait": "🇰🇼", "Kyrgyzstan": "🇰🇬", "Laos": "🇱🇦", "Latvia": "🇱🇻", "Lebanon": "🇱🇧",
    "Lesotho": "🇱🇸", "Liberia": "🇱🇷", "Libya": "🇱🇾", "Liechtenstein": "🇱🇮", "Lithuania": "🇱🇹",
    "Luxembourg": "🇱🇺", "Madagascar": "🇲🇬", "Malawi": "🇲🇼", "Malaysia": "🇲🇾", "Maldives": "🇲🇻",
    "Mali": "🇲🇱", "Malta": "🇲🇹", "Marshall Islands": "🇲🇭", "Mauritania": "🇲🇷",
    "Mauritius": "🇲🇺", "Mexico": "🇲🇽", "Micronesia": "🇫🇲", "Moldova": "🇲🇩", "Monaco": "🇲🇨",
    "Mongolia": "🇲🇳", "Montenegro": "🇲🇪", "Morocco": "🇲🇦", "Mozambique": "🇲🇿", "Myanmar": "🇲🇲",
    "Namibia": "🇳🇦", "Nauru": "🇳🇷", "Nepal": "🇳🇵", "Netherlands": "🇳🇱", "New Zealand": "🇳🇿",
    "Nicaragua": "🇳🇮", "Niger": "🇳🇪", "Nigeria": "🇳🇬", "North Korea": "🇰🇵",
    "North Macedonia": "🇲🇰", "Norfolk Island": "🇳🇫", "Norway": "🇳🇴", "Oman": "🇴🇲",
    "Pakistan": "🇵🇰", "Palau": "🇵🇼", "Palestine": "🇵🇸", "Panama": "🇵🇦",
    "Papua New Guinea": "🇵🇬", "Paraguay": "🇵🇾", "Peru": "🇵🇪", "Philippines": "🇵🇭",
    "Poland": "🇵🇱", "Portugal": "🇵🇹", "Qatar": "🇶🇦", "Romania": "🇷🇴", "Russia": "🇷🇺",
    "Rwanda": "🇷🇼", "Saint Kitts and Nevis": "🇰🇳", "Saint Lucia": "🇱🇨",
    "Saint Vincent and the Grenadines": "🇻🇨", "Samoa": "🇼🇸", "San Marino": "🇸🇲",
    "Sao Tome and Principe": "🇸🇹", "Saudi Arabia": "🇸🇦", "Senegal": "🇸🇳", "Serbia": "🇷🇸",
    "Seychelles": "🇸🇨", "Sierra Leone": "🇸🇱", "Singapore": "🇸🇬", "Slovakia": "🇸🇰",
    "Slovenia": "🇸🇮", "Solomon Islands": "🇸🇧", "Somalia": "🇸🇴", "South Africa": "🇿🇦",
    "South Korea": "🇰🇷", "South Sudan": "🇸🇸", "Spain": "🇪🇸", "Sri Lanka": "🇱🇰",
    "Sudan": "🇸🇩", "Suriname": "🇸🇷", "Sweden": "🇸🇪", "Switzerland": "🇨🇭", "Syria": "🇸🇾",
    "Tajikistan": "🇹🇯", "Tanzania": "🇹🇿", "Thailand": "🇹🇭", "Timor-Leste": "🇹🇱",
    "Togo": "🇹🇬", "Tonga": "🇹🇴", "Trinidad and Tobago": "🇹🇹", "Tunisia": "🇹🇳",
    "Turkey": "🇹🇷", "Turkmenistan": "🇹🇲", "Tuvalu": "🇹🇻", "Uganda": "🇺🇬", "Ukraine": "🇺🇦",
    "United Arab Emirates": "🇦🇪", "United Kingdom": "🇬🇧", "United States": "🇺🇸",
    "Uruguay": "🇺🇾", "Uzbekistan": "🇺🇿", "Vanuatu": "🇻🇺", "Vatican City": "🇻🇦",
    "Venezuela": "🇻🇪", "Vietnam": "🇻🇳", "Yemen": "🇾🇪", "Zambia": "🇿🇲", "Zimbabwe": "🇿🇼",
    "Antarctica": "🇦🇶"
}

def get_flag(country_name):
    return COUNTRY_FLAGS.get(country_name, "🏳️")

# ---------- DB ----------

def get_db():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set in environment variables")
    
    # Попытка подключения с повторами (для Railway)
    max_retries = 10
    for i in range(max_retries):
        try:
            conn = psycopg.connect(DATABASE_URL)
            return conn
        except Exception as e:
            if i == max_retries - 1:
                raise e
            print(f"DB connection attempt {i+1} failed: {e}. Retrying in 2s...")
            time.sleep(2)

def init_db():
    db = get_db()
    c = db.cursor()

    # Добавлено поле country
    c.execute("""
    CREATE TABLE IF NOT EXISTS users(
      id SERIAL PRIMARY KEY,
      username TEXT UNIQUE,
      password TEXT,
      nickname TEXT,
      avatar TEXT DEFAULT 'default.png',
      theme TEXT DEFAULT 'matrix',
      timezone TEXT DEFAULT 'UTC',
      country TEXT DEFAULT 'United States'
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

    # Проверка наличия колонки country (если таблица уже есть)
    try:
        c.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS country TEXT DEFAULT 'United States'")
        db.commit()
    except Exception as e:
        print(f"Could not alter table for country: {e}")
        db.rollback()

    db.commit()
    db.close()

# Вызываем init_db только если есть DATABASE_URL
if DATABASE_URL:
    try:
        init_db()
        print("Database initialized successfully.")
    except Exception as e:
        print(f"Critical Error initializing database: {e}")

# ---------- THEMES ----------

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
            
            avatar = "default.png" # Дефолтная аватарка
            
            # Обработка загруженного файла аватарки
            if 'avatar_file' in request.files:
                file = request.files['avatar_file']
                if file and file.filename != '':
                    ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else 'png'
                    new_filename = f"u{new_id}_{uuid.uuid4().hex[:8]}.{ext}"
                    filepath = os.path.join(app.config['UPLOAD_FOLDER'], new_filename)
                    file.save(filepath)
                    avatar = new_filename
            
            country = request.form.get("country", "United States")

            c.execute(
              "INSERT INTO users(id, username, password, avatar, nickname, country) VALUES(%s,%s,%s,%s,%s,%s)",
              (
                new_id,
                request.form["username"],
                request.form["password"],
                avatar,
                request.form["username"],
                country
              )
            )
            db.commit()
        except psycopg.IntegrityError:
             db.close()
             return "Username already exists!", 400
        db.close()
        return redirect("/")
    
    # Генерация опций стран
    country_options = "".join([f'<option value="{c}">{c}</option>' for c in COUNTRIES_LIST])
    
    return f"""
    <body style="background:#000;color:#0f0;font-family:Courier New">
    <h3>Register</h3>
    <form method=post enctype="multipart/form-data">
      <input name=username placeholder=username><br>
      <input name=password type=password placeholder=password><br>
      <label>Upload Avatar: <input type=file name=avatar_file accept="image/*"></label><br>
      <label>Country: 
        <select name=country>
          {country_options}
        </select>
      </label><br>
      <button>Register</button>
    </form>
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
    c.execute("SELECT nickname,avatar,theme,timezone,country FROM users WHERE id=%s",(session["user_id"],))
    nick,avatar,theme,tz,country=c.fetchone()
    colors=THEMES.get(theme,THEMES["matrix"])
    user_flag = get_flag(country)
    
    # Получаем список ID друзей
    c.execute("SELECT friend_id FROM friendships WHERE user_id=%s", (session["user_id"],))
    friend_ids = [row[0] for row in c.fetchall()]
    
    # Получаем историю сообщений
    c.execute("""
        SELECT m.content, m.created_at, u.nickname, u.avatar, u.timezone, u.id, u.country
        FROM messages m
        JOIN users u ON m.user_id = u.id
        ORDER BY m.created_at ASC
        LIMIT 100
    """)
    messages = []
    for row in c.fetchall():
        content, created_at, msg_nick, msg_avatar, msg_tz, msg_user_id, msg_country = row
        local_time = created_at.astimezone(ZoneInfo(tz)).strftime("%H:%M:%S")
        messages.append({
            "text": content,
            "time": local_time,
            "nick": msg_nick,
            "avatar": msg_avatar,
            "user_id": msg_user_id,
            "flag": get_flag(msg_country)
        })
    
    db.close()

    messages_html = ""
    for m in messages:
        is_friend = m["user_id"] in friend_ids
        style = 'border: 2px solid #0f0; background: rgba(0, 255, 0, 0.1); padding: 5px;' if is_friend else ''
        nick_link = f'<a href="/profile/{m["user_id"]}" style="color: inherit; text-decoration: none;">{m["nick"]}</a>'
        messages_html += f'''
        <div style="{style}">
          <img src="/static/avatars/{m["avatar"]}" width=32 onerror="this.src='data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><circle cx=%2250%22 cy=%2250%22 r=%2250%22 fill=%22%23555%22/></svg>'">
          <b>{nick_link}</b> {m["flag"]} <small>(ID: {m["user_id"]})</small>
          <small>{m["flag"]} {m["time"]}</small><br>
          {m["text"]}
        </div>'''

    return f"""
<!doctype html>
<body style="margin:0;background:{colors[0]};color:{colors[1]};font-family:Courier New">
<div style="padding:10px;border-bottom:1px solid {colors[1]}">
  {nick} {user_flag} (ID: {session['user_id']})
  <a href=/settings>Settings</a>
  <a href=/leaderboard>Leaderboard</a>
  <a href=/logout>Logout</a>
</div>

<div id=chat style="height:70vh;overflow:auto;padding:10px">{messages_html}</div>

<div style="display:flex">
  <input id=msg style="flex:1">
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
    const isFriend = friendIds.includes(m.user_id);
    const style = isFriend ? 'border: 2px solid #0f0; background: rgba(0, 255, 0, 0.1); padding: 5px;' : '';
    const nickLink = `<a href="/profile/${{m.user_id}}" style="color: inherit; text-decoration: none;">${{m.nick}}</a>`;
    const avatarSrc = `/static/avatars/${{m.avatar}}`;
    const fallbackAvatar = 'data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><circle cx=%2250%22 cy=%2250%22 r=%2250%22 fill=%22%23555%22/></svg>';
    
    chat.innerHTML+=`
    <div style="${{style}}">
      <img src="${{avatarSrc}}" width=32 onerror="this.src='${{fallbackAvatar}}'">
      <b>${{nickLink}}</b> ${{m.flag}} <small>(ID: ${{m.user_id}})</small>
      <small>${{m.flag}} ${{m.time}}</small><br>
      ${{m.text}}
    </div>`;
    chat.scrollTop=chat.scrollHeight;
}});

function send(){{
  const text = msg.value.trim();
  if (text) {{
    s.emit("msg", text);
    msg.value="";
  }}
}}
</script>
</body>
"""

# ---------- SOCKET (обработка сообщений) ----------

@socketio.on("msg")
def msg(text):
    user_id = connected_users.get(request.sid)
    if user_id is None:
        print(f"Message received from unknown SID {request.sid}, ignoring.")
        return

    db = None
    try:
        db = get_db()
        c = db.cursor()
        c.execute("""
          SELECT nickname, avatar, theme, timezone, country
          FROM users WHERE id=%s
        """, (user_id,))
        user_data = c.fetchone()

        if not user_data:
            print(f"User data not found for ID {user_id}, SID {request.sid}, ignoring message.")
            return

        nick, avatar, theme, tz, country = user_data
        flag = get_flag(country)

        c.execute("INSERT INTO messages(user_id,content) VALUES(%s,%s)", (user_id, text))
        db.commit()

        now = datetime.now(ZoneInfo(tz)).strftime("%H:%M:%S")

        emit("msg",{
          "nick": nick,
          "avatar": avatar,
          "text": text,
          "time": now,
          "user_id": user_id,
          "flag": flag
        }, broadcast=True)

    except Exception as e:
        print(f"Error processing message for user {user_id}, SID {request.sid}: {e}")
    finally:
        if db:
            db.close()

# ---------- PROFILE ----------

@app.route("/profile/<int:user_id>")
def profile(user_id):
    if "user_id" not in session:
        return redirect("/")
    
    current_user_id = session["user_id"]
    db = get_db()
    c = db.cursor()
    
    c.execute("SELECT id, username, nickname, avatar, theme, country FROM users WHERE id=%s", (user_id,))
    user = c.fetchone()
    if not user:
        db.close()
        return "User not found", 404
    
    u_id, u_username, u_nickname, u_avatar, u_theme, u_country = user
    colors = THEMES.get(u_theme, THEMES["matrix"])
    flag = get_flag(u_country)
    
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
        friends_html += f'<a href="/profile/{f_id}"><img src="/static/avatars/{f_av}" width=40 style="border-radius:50%" onerror="this.src=\'data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><circle cx=%2250%22 cy=%2250%22 r=%2250%22 fill=%22%23555%22/></svg>\'"></a> '
    
    action_button = ""
    if current_user_id != user_id:
        if is_friend:
            action_button = f'<a href="/remove_friend/{user_id}" style="color:red">Remove Friend</a>'
        else:
            action_button = f'<a href="/add_friend/{user_id}" style="color:#0f0">Add Friend</a>'

    return f"""
    <body style="margin:0;background:{colors[0]};color:{colors[1]};font-family:Courier New">
    <div style="padding:20px">
      <a href="/chat">Back to Chat</a>
      <hr>
      <center>
        <img src="/static/avatars/{u_avatar}" width=100 style="border-radius:50%; border: 4px solid {colors[1]}" onerror="this.src='data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><circle cx=%2250%22 cy=%2250%22 r=%2250%22 fill=%22%23555%22/></svg>'">
        <h2>{u_nickname} {flag}</h2>
        <p>@{u_username} (ID: {u_id})</p>
        <p>Country: {u_country}</p>
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
    if "user_id" not in session:
        return redirect("/")
    
    user_id = session["user_id"]
    if user_id == friend_id:
        return "Cannot add yourself as a friend", 400
        
    db = get_db()
    c = db.cursor()
    try:
        c.execute("INSERT INTO friendships(user_id, friend_id) VALUES(%s, %s)", (user_id, friend_id))
        db.commit()
    except psycopg.IntegrityError:
        pass
    finally:
        db.close()
        
    return redirect(f"/profile/{friend_id}")

@app.route("/remove_friend/<int:friend_id>")
def remove_friend(friend_id):
    if "user_id" not in session:
        return redirect("/")
    
    user_id = session["user_id"]
    db = get_db()
    c = db.cursor()
    c.execute("DELETE FROM friendships WHERE user_id=%s AND friend_id=%s", (user_id, friend_id))
    db.commit()
    db.close()
    
    return redirect(f"/profile/{friend_id}")

# ---------- SETTINGS ----------

@app.route("/settings", methods=["GET","POST"])
def settings():
    if "user_id" not in session:
        return redirect("/")
    
    db=get_db(); c=db.cursor()
    if request.method=="POST":
        avatar = request.form.get("avatar", "")
        
        if 'avatar_file' in request.files:
            file = request.files['avatar_file']
            if file and file.filename != '':
                ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else 'png'
                new_filename = f"u{session['user_id']}_{uuid.uuid4().hex[:8]}.{ext}"
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], new_filename)
                file.save(filepath)
                avatar = new_filename
        
        c.execute("""
        UPDATE users SET nickname=%s,avatar=%s,theme=%s,timezone=%s,country=%s
        WHERE id=%s
        """, (
          request.form["nickname"],
          avatar,
          request.form["theme"],
          request.form["timezone"],
          request.form["country"],
          session["user_id"]
        ))
        db.commit()
        db.close()
        return redirect("/chat")

    c.execute("SELECT nickname,avatar,theme,timezone,country FROM users WHERE id=%s",(session["user_id"],))
    u=c.fetchone()
    db.close()
    
    country_options = "".join([f'<option value="{c}"{" selected" if c == u[4] else ""}>{c}</option>' for c in COUNTRIES_LIST])
    theme_options = "".join([f'<option value="{t}"{" selected" if t == u[2] else ""}>{t.title()}</option>' for t in THEMES.keys()])
    tz_list = sorted(list(available_timezones()))
    tz_options = "".join([f'<option value="{tz}"{" selected" if tz == u[3] else ""}>{tz}</option>' for tz in tz_list])

    return f"""
    <body style="background:#000;color:#0f0;font-family:Courier New">
    <h3>Settings</h3>
    <form method=post enctype="multipart/form-data">
      Nick:<input name=nickname value="{u[0]}"><br>
      Upload Avatar: <input type=file name=avatar_file accept="image/*"><br>
      Current Avatar: <img src="/static/avatars/{u[1]}" width=50 onerror="this.src='data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><circle cx=%2250%22 cy=%2250%22 r=%2250%22 fill=%22%23555%22/></svg>'"><br>
      Country: <select name=country>{country_options}</select><br>
      Theme:<select name=theme>{theme_options}</select><br>
      TZ:<select name=timezone>{tz_options}</select><br>
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


