import os
import time
import psycopg
from flask import Flask, request, session, redirect, send_from_directory, url_for
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

# ---------- DB ----------

def get_db():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set in environment variables")
    
    # Попытки подключения с retry, так как БД может запускаться дольше приложения
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

    c.execute("""
    CREATE TABLE IF NOT EXISTS users(
      id SERIAL PRIMARY KEY,
      username TEXT UNIQUE,
      password TEXT,
      nickname TEXT,
      avatar TEXT, -- Теперь может быть пустым, тогда показываем флаг
      country TEXT DEFAULT 'World',
      theme TEXT DEFAULT 'matrix',
      timezone TEXT DEFAULT 'UTC'
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

    db.commit()
    db.close()
    print("Database initialized successfully.")

# Вызываем init_db только если есть DATABASE_URL
if DATABASE_URL:
    try:
        init_db()
    except Exception as e:
        print(f"Critical Error initializing database: {e}")

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

# Полный список стран для кодов флагов (используем стандартные ISO коды или названия для emoji)
# Простой маппинг названия -> Emoji флага
COUNTRY_FLAGS = {
    "Afghanistan": "🇦🇫", "Albania": "🇦🇱", "Algeria": "🇩🇿", "Andorra": "🇦🇩", "Angola": "🇦🇴",
    "Antigua and Barbuda": "🇦🇬", "Argentina": "🇦🇷", "Armenia": "🇦🇲", "Australia": "🇦🇺", "Austria": "🇦🇹",
    "Azerbaijan": "🇦🇿", "Bahamas": "🇧🇸", "Bahrain": "🇧🇭", "Bangladesh": "🇧🇩", "Barbados": "🇧🇧",
    "Belarus": "🇧🇾", "Belgium": "🇧🇪", "Belize": "🇧🇿", "Benin": "🇧🇯", "Bhutan": "🇧🇹",
    "Bolivia": "🇧🇴", "Bosnia and Herzegovina": "🇧🇦", "Botswana": "🇧🇼", "Brazil": "🇧🇷", "Brunei": "🇧🇳",
    "Bulgaria": "🇧🇬", "Burkina Faso": "🇧🇫", "Burundi": "🇧🇮", "Cabo Verde": "🇨🇻", "Cambodia": "🇰🇭",
    "Cameroon": "🇨🇲", "Canada": "🇨🇦", "Central African Republic": "🇨🇫", "Chad": "🇹🇩", "Chile": "🇨🇱",
    "China": "🇨🇳", "Colombia": "🇨🇴", "Comoros": "🇰🇲", "Congo (Brazzaville)": "🇨🇬", "Congo (Kinshasa)": "🇨🇩",
    "Costa Rica": "🇨🇷", "Croatia": "🇭🇷", "Cuba": "🇨🇺", "Cyprus": "🇨🇾", "Czechia": "🇨🇿",
    "Denmark": "🇩🇰", "Djibouti": "🇩🇯", "Dominica": "🇩🇲", "Dominican Republic": "🇩🇴", "Ecuador": "🇪🇨",
    "Egypt": "🇪🇬", "El Salvador": "🇸🇻", "Equatorial Guinea": "🇬🇶", "Eritrea": "🇪🇷", "Estonia": "🇪🇪",
    "Eswatini": "🇸🇿", "Ethiopia": "🇪🇹", "Fiji": "🇫🇯", "Finland": "🇫🇮", "France": "🇫🇷",
    "Gabon": "🇬🇦", "Gambia": "🇬🇲", "Georgia": "🇬🇪", "Germany": "🇩🇪", "Ghana": "🇬🇭",
    "Greece": "🇬🇷", "Grenada": "🇬🇩", "Guatemala": "🇬🇹", "Guinea": "🇬🇳", "Guinea-Bissau": "🇬🇼",
    "Guyana": "🇬🇾", "Haiti": "🇭🇹", "Honduras": "🇭🇳", "Hungary": "🇭🇺", "Iceland": "🇮🇸",
    "India": "🇮🇳", "Indonesia": "🇮🇩", "Iran": "🇮🇷", "Iraq": "🇮🇶", "Ireland": "🇮🇪",
    "Israel": "🇮🇱", "Italy": "🇮🇹", "Jamaica": "🇯🇲", "Japan": "🇯🇵", "Jordan": "🇯🇴",
    "Kazakhstan": "🇰🇿", "Kenya": "🇰🇪", "Kiribati": "🇰🇮", "Kuwait": "🇰🇼", "Kyrgyzstan": "🇰🇬",
    "Laos": "🇱🇦", "Latvia": "🇱🇻", "Lebanon": "🇱🇧", "Lesotho": "🇱🇸", "Liberia": "🇱🇷",
    "Libya": "🇱🇾", "Liechtenstein": "🇱🇮", "Lithuania": "🇱🇹", "Luxembourg": "🇱🇺", "Madagascar": "🇲🇬",
    "Malawi": "🇲🇼", "Malaysia": "🇲🇾", "Maldives": "🇲🇻", "Mali": "🇲🇱", "Malta": "🇲🇹",
    "Marshall Islands": "🇲🇭", "Mauritania": "🇲🇷", "Mauritius": "🇲🇺", "Mexico": "🇲🇽", "Micronesia": "🇫🇲",
    "Moldova": "🇲🇩", "Monaco": "🇲🇨", "Mongolia": "🇲🇳", "Montenegro": "🇲🇪", "Morocco": "🇲🇦",
    "Mozambique": "🇲🇿", "Myanmar": "🇲🇲", "Namibia": "🇳🇦", "Nauru": "🇳🇷", "Nepal": "🇳🇵",
    "Netherlands": "🇳🇱", "New Zealand": "🇳🇿", "Nicaragua": "🇳🇮", "Niger": "🇳🇪", "Nigeria": "🇳🇬",
    "North Korea": "🇰🇵", "North Macedonia": "🇲🇰", "Norfolk Island": "🇳🇫", "Norway": "🇳🇴", "Oman": "🇴🇲",
    "Pakistan": "🇵🇰", "Palau": "🇵🇼", "Palestine": "🇵🇸", "Panama": "🇵🇦", "Papua New Guinea": "🇵🇬",
    "Paraguay": "🇵🇾", "Peru": "🇵🇪", "Philippines": "🇵🇭", "Poland": "🇵🇱", "Portugal": "🇵🇹",
    "Qatar": "🇶🇦", "Romania": "🇷🇴", "Russia": "🇷🇺", "Rwanda": "🇷🇼", "Saint Kitts and Nevis": "🇰🇳",
    "Saint Lucia": "🇱🇨", "Saint Vincent and the Grenadines": "🇻🇨", "Samoa": "🇼🇸", "San Marino": "🇸🇲",
    "Sao Tome and Principe": "🇸🇹", "Saudi Arabia": "🇸🇦", "Senegal": "🇸🇳", "Serbia": "🇷🇸", "Seychelles": "🇸🇨",
    "Sierra Leone": "🇸🇱", "Singapore": "🇸🇬", "Slovakia": "🇸🇰", "Slovenia": "🇸🇮", "Solomon Islands": "🇸🇧",
    "Somalia": "🇸🇴", "South Africa": "🇿🇦", "South Korea": "🇰🇷", "South Sudan": "🇸🇸", "Spain": "🇪🇸",
    "Sri Lanka": "🇱🇰", "Sudan": "🇸🇩", "Suriname": "🇸🇷", "Sweden": "🇸🇪", "Switzerland": "🇨🇭",
    "Syria": "🇸🇾", "Tajikistan": "🇹🇯", "Tanzania": "🇹🇿", "Thailand": "🇹🇭", "Timor-Leste": "🇹🇱",
    "Togo": "🇹🇬", "Tonga": "🇹🇴", "Trinidad and Tobago": "🇹🇹", "Tunisia": "🇹🇳", "Turkey": "🇹🇷",
    "Turkmenistan": "🇹🇲", "Tuvalu": "🇹🇻", "Uganda": "🇺🇬", "Ukraine": "🇺🇦", "United Arab Emirates": "🇦🇪",
    "United Kingdom": "🇬🇧", "United States": "🇺🇸", "Uruguay": "🇺🇾", "Uzbekistan": "🇺🇿", "Vanuatu": "🇻🇺",
    "Vatican City": "🇻🇦", "Venezuela": "🇻🇪", "Vietnam": "🇻🇳", "Yemen": "🇾🇪", "Zambia": "🇿🇲",
    "Zimbabwe": "🇿🇼", "Antarctica": "🇦🇶"
}

COUNTRIES_LIST = sorted(COUNTRY_FLAGS.keys())

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
            
            avatar = None # По умолчанию нет аватарки, будет флаг
            country = request.form.get("country", "World")
            
            # Обработка загруженного файла аватарки
            if 'avatar_file' in request.files:
                file = request.files['avatar_file']
                if file and file.filename != '':
                    ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else 'png'
                    new_filename = f"u{new_id}_{uuid.uuid4().hex[:8]}.{ext}"
                    filepath = os.path.join(app.config['UPLOAD_FOLDER'], new_filename)
                    file.save(filepath)
                    avatar = new_filename
            
            c.execute(
              "INSERT INTO users(id, username, password, avatar, country, nickname) VALUES(%s,%s,%s,%s,%s,%s)",
              (
                new_id,
                request.form["username"],
                request.form["password"],
                avatar,
                country,
                request.form["username"]
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
    tz_list = sorted(list(available_timezones()))
    tz_options = "".join([f'<option value="{tz}">{tz}</option>' for tz in tz_list])
    
    return f"""
    <body style="background:#000;color:#0f0;font-family:Courier New">
    <h3>Register</h3>
    <form method=post enctype="multipart/form-data">
      <input name=username placeholder=username required><br>
      <input name=password type=password placeholder=password required><br>
      <label>Country:<br>
        <select name=country style="width:200px">
          <option value="" disabled selected>Select your country</option>
          {country_options}
        </select>
      </label><br><br>
      <label>Upload Avatar (Optional): <input type=file name=avatar_file accept="image/*"></label><br>
      <small>If no avatar is uploaded, your country flag will be shown.</small><br><br>
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
    c.execute("SELECT nickname,avatar,country,theme,timezone FROM users WHERE id=%s",(session["user_id"],))
    nick,avatar,country,theme,tz=c.fetchone()
    colors=THEMES.get(theme,THEMES["matrix"])
    
    # Получаем список ID друзей
    c.execute("SELECT friend_id FROM friendships WHERE user_id=%s", (session["user_id"],))
    friend_ids = [row[0] for row in c.fetchall()]
    
    # Получаем историю сообщений
    c.execute("""
        SELECT m.content, m.created_at, u.nickname, u.avatar, u.country, u.timezone, u.id
        FROM messages m
        JOIN users u ON m.user_id = u.id
        ORDER BY m.created_at ASC
        LIMIT 100
    """)
    messages = []
    for row in c.fetchall():
        content, created_at, msg_nick, msg_avatar, msg_country, msg_tz, msg_user_id = row
        
        # Определяем, что показывать: аватарку или флаг
        display_img = ""
        if msg_avatar:
            display_img = f'<img src="/static/avatars/{msg_avatar}" width=32 style="border-radius:50%">'
        else:
            flag = COUNTRY_FLAGS.get(msg_country, "🏳️")
            display_img = f'<span style="font-size:24px">{flag}</span>'
            
        local_time = created_at.astimezone(ZoneInfo(tz)).strftime("%H:%M:%S")
        messages.append({
            "text": content,
            "time": local_time,
            "nick": msg_nick,
            "img_html": display_img,
            "user_id": msg_user_id
        })
    
    db.close()

    messages_html = ""
    for m in messages:
        is_friend = m["user_id"] in friend_ids
        style = 'border: 2px solid #0f0; background: rgba(0, 255, 0, 0.1); padding: 5px;' if is_friend else ''
        nick_link = f'<a href="/profile/{m["user_id"]}" style="color: inherit; text-decoration: none;">{m["nick"]}</a>'
        messages_html += f'''
        <div style="{style} margin-bottom: 8px;">
          {m["img_html"]}
          <b>{nick_link}</b> <small>(ID: {m["user_id"]})</small>
          <small>{m["time"]}</small><br>
          {m["text"]}
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
    
    chat.innerHTML+=`
    <div style="${{style}} margin-bottom: 8px;">
      ${{m.img_html}}
      <b>${{nickLink}}</b> <small>(ID: ${{m.user_id}})</small>
      <small>${{m.time}}</small><br>
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
          SELECT nickname, avatar, country, theme, timezone
          FROM users WHERE id=%s
        """, (user_id,))
        user_data = c.fetchone()

        if not user_data:
            print(f"User data not found for ID {user_id}, SID {request.sid}, ignoring message.")
            return

        nick, avatar, country, theme, tz = user_data

        # Формируем HTML для картинки/флага прямо здесь для отправки
        if avatar:
            img_html = f'<img src="/static/avatars/{avatar}" width=32 style="border-radius:50%">'
        else:
            flag = COUNTRY_FLAGS.get(country, "🏳️")
            img_html = f'<span style="font-size:24px">{flag}</span>'

        c.execute("INSERT INTO messages(user_id,content) VALUES(%s,%s)", (user_id, text))
        db.commit()

        now = datetime.now(ZoneInfo(tz)).strftime("%H:%M:%S")

        emit("msg",{
          "nick": nick,
          "img_html": img_html,
          "text": text,
          "time": now,
          "user_id": user_id
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
    
    c.execute("SELECT id, username, nickname, avatar, country, theme FROM users WHERE id=%s", (user_id,))
    user = c.fetchone()
    if not user:
        db.close()
        return "User not found", 404
    
    u_id, u_username, u_nickname, u_avatar, u_country, u_theme = user
    colors = THEMES.get(u_theme, THEMES["matrix"])
    
    # Определяем изображение профиля
    if u_avatar:
        profile_img = f'<img src="/static/avatars/{u_avatar}" width=100 style="border-radius:50%; border: 4px solid {colors[1]}">'
    else:
        flag = COUNTRY_FLAGS.get(u_country, "🏳️")
        profile_img = f'<div style="font-size:80px; line-height:100px; border: 4px solid {colors[1]}; border-radius:50%; width:100px; height:100px; display:inline-block;">{flag}</div>'

    c.execute("SELECT COUNT(*) FROM messages WHERE user_id=%s", (user_id,))
    msg_count = c.fetchone()[0]
    
    c.execute("""
      SELECT u.id, u.username, u.nickname, u.avatar, u.country
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
    for f_id, f_user, f_nick, f_av, f_country in friends:
        if f_av:
            f_img = f'<img src="/static/avatars/{f_av}" width=40 style="border-radius:50%">'
        else:
            f_flag = COUNTRY_FLAGS.get(f_country, "🏳️")
            f_img = f'<span style="font-size:30px">{f_flag}</span>'
        friends_html += f'<a href="/profile/{f_id}">{f_img}</a> '
    
    action_button = ""
    if current_user_id != user_id:
        if is_friend:
            action_button = f'<a href="/remove_friend/{user_id}" style="color:red">Remove Friend</a>'
        else:
            action_button = f'<a href="/add_friend/{user_id}" style="color:#0f0">Add Friend</a>'

    country_display = f"{u_country} {COUNTRY_FLAGS.get(u_country, '')}"

    return f"""
    <body style="margin:0;background:{colors[0]};color:{colors[1]};font-family:Courier New">
    <div style="padding:20px">
      <a href="/chat">Back to Chat</a>
      <hr>
      <center>
        {profile_img}
        <h2>{u_nickname}</h2>
        <p>@{u_username} (ID: {u_id})</p>
        <p>Country: {country_display}</p>
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
        if avatar == "": avatar = None # Разрешаем убрать аватарку
        
        # Обработка загруженного файла
        if 'avatar_file' in request.files:
            file = request.files['avatar_file']
            if file and file.filename != '':
                ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else 'png'
                new_filename = f"u{session['user_id']}_{uuid.uuid4().hex[:8]}.{ext}"
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], new_filename)
                file.save(filepath)
                avatar = new_filename
        elif request.form.get("remove_avatar") == "on":
            avatar = None

        c.execute("""
        UPDATE users SET nickname=%s,avatar=%s,country=%s,theme=%s,timezone=%s
        WHERE id=%s
        """, (
          request.form["nickname"],
          avatar,
          request.form["country"],
          request.form["theme"],
          request.form["timezone"],
          session["user_id"]
        ))
        db.commit()
        db.close()
        return redirect("/chat")

    c.execute("SELECT nickname,avatar,country,theme,timezone FROM users WHERE id=%s",(session["user_id"],))
    u=c.fetchone()
    db.close()
    
    country_options = "".join([f'<option value="{c}"{" selected" if c == u[2] else ""}>{c}</option>' for c in COUNTRIES_LIST])
    theme_options = "".join([f'<option value="{t}"{" selected" if t == u[3] else ""}>{t.title()}</option>' for t in THEMES.keys()])
    tz_list = sorted(list(available_timezones()))
    tz_options = "".join([f'<option value="{tz}"{" selected" if tz == u[4] else ""}>{tz}</option>' for tz in tz_list])

    current_avatar_html = ""
    if u[1]:
        current_avatar_html = f'Current Avatar: <img src="/static/avatars/{u[1]}" width=50><br><label><input type=checkbox name=remove_avatar> Remove Avatar</label><br>'
    else:
        current_avatar_html = f'Current Avatar: Flag of {u[2]} ({COUNTRY_FLAGS.get(u[2], "")})<br>'

    return f"""
    <body style="background:#000;color:#0f0;font-family:Courier New">
    <h3>Settings</h3>
    <form method=post enctype="multipart/form-data">
      Nick:<input name=nickname value="{u[0]}"><br>
      Country:<br>
        <select name=country style="width:200px">
          {country_options}
        </select><br><br>
      Upload New Avatar: <input type=file name=avatar_file accept="image/*"><br>
      {current_avatar_html}
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






