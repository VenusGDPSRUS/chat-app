import os
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
      avatar TEXT DEFAULT 'a1.png',
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

# Вызываем init_db только если есть DATABASE_URL, иначе пропускаем (для локальной проверки)
if DATABASE_URL:
    try:
        init_db()
    except Exception as e:
        print(f"Warning: Could not initialize database: {e}")

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
            # Получаем следующий доступный ID вручную, чтобы он был порядковым и предсказуемым
            c.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM users")
            new_id = c.fetchone()[0]
            
            avatar = request.form.get("avatar","a1.png")
            
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
              "INSERT INTO users(id, username, password, avatar, nickname) VALUES(%s,%s,%s,%s,%s)",
              (
                new_id,
                request.form["username"],
                request.form["password"],
                avatar,
                request.form["username"]
              )
            )
            db.commit()
        except psycopg.IntegrityError:
             db.close()
             return "Username already exists!", 400
        db.close()
        return redirect("/")
    
    # Список доступных тем и часовых поясов
    theme_options = "".join([f'<option value="{t}">{t.title()}</option>' for t in THEMES.keys()])
    tz_list = sorted(list(available_timezones()))
    tz_options = "".join([f'<option value="{tz}">{tz}</option>' for tz in tz_list])
    
    return f"""
    <body style="background:#000;color:#0f0;font-family:Courier New">
    <h3>Register</h3>
    <form method=post enctype="multipart/form-data">
      <input name=username placeholder=username><br>
      <input name=password type=password placeholder=password><br>
      <label>Upload Avatar: <input type=file name=avatar_file accept="image/*"></label><br>
      <small>Or select default:</small><br>
      <input type=hidden name=avatar id=avatar>
      <img src=/static/avatars/a1.png onclick="pick('a1.png')" style="cursor:pointer;border:2px solid transparent" onmouseover="this.style.border='2px solid #0f0'" onmouseout="this.style.border='2px solid transparent'">
      <img src=/static/avatars/a2.png onclick="pick('a2.png')" style="cursor:pointer;border:2px solid transparent" onmouseover="this.style.border='2px solid #0f0'" onmouseout="this.style.border='2px solid transparent'">
      <img src=/static/avatars/a3.png onclick="pick('a3.png')" style="cursor:pointer;border:2px solid transparent" onmouseover="this.style.border='2px solid #0f0'" onmouseout="this.style.border='2px solid transparent'"><br>
      <button>Register</button>
    </form>
    <script>
      function pick(a){{avatar.value=a;}}
    </script>
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
    c.execute("SELECT nickname,avatar,theme,timezone FROM users WHERE id=%s",(session["user_id"],))
    nick,avatar,theme,tz=c.fetchone()
    colors=THEMES.get(theme,THEMES["matrix"])
    
    # Получаем список ID друзей
    c.execute("SELECT friend_id FROM friendships WHERE user_id=%s", (session["user_id"],))
    friend_ids = [row[0] for row in c.fetchall()]
    
    # Получаем историю сообщений
    c.execute("""
        SELECT m.content, m.created_at, u.nickname, u.avatar, u.timezone, u.id
        FROM messages m
        JOIN users u ON m.user_id = u.id
        ORDER BY m.created_at ASC
        LIMIT 100
    """)
    messages = []
    for row in c.fetchall():
        content, created_at, msg_nick, msg_avatar, msg_tz, msg_user_id = row
        local_time = created_at.astimezone(ZoneInfo(tz)).strftime("%H:%M:%S")
        messages.append({
            "text": content,
            "time": local_time,
            "nick": msg_nick,
            "avatar": msg_avatar,
            "user_id": msg_user_id
        })
    
    db.close()

    messages_html = ""
    for m in messages:
        is_friend = m["user_id"] in friend_ids
        style = 'border: 2px solid #0f0; background: rgba(0, 255, 0, 0.1); padding: 5px;' if is_friend else ''
        nick_link = f'<a href="/profile/{m["user_id"]}" style="color: inherit; text-decoration: none;">{m["nick"]}</a>'
        messages_html += f'''
        <div style="{style}">
          <img src="/static/avatars/{m["avatar"]}" width=32>
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
const friendIds = {friend_ids}; // Передаем список друзей в JS

s.on("connect", () => {{
    console.log("Connected to server via Socket.IO");
}});

s.on("msg", m => {{
    const isFriend = friendIds.includes(m.user_id);
    const style = isFriend ? 'border: 2px solid #0f0; background: rgba(0, 255, 0, 0.1); padding: 5px;' : '';
    const nickLink = `<a href="/profile/${{m.user_id}}" style="color: inherit; text-decoration: none;">${{m.nick}}</a>`;
    
    chat.innerHTML+=`
    <div style="${{style}}">
      <img src="/static/avatars/${{m.avatar}}" width=32>
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
          SELECT nickname, avatar, theme, timezone
          FROM users WHERE id=%s
        """, (user_id,))
        user_data = c.fetchone()

        if not user_data:
            print(f"User data not found for ID {user_id}, SID {request.sid}, ignoring message.")
            return

        nick, avatar, theme, tz = user_data

        c.execute("INSERT INTO messages(user_id,content) VALUES(%s,%s)", (user_id, text))
        db.commit()

        now = datetime.now(ZoneInfo(tz)).strftime("%H:%M:%S")

        emit("msg",{
          "nick": nick,
          "avatar": avatar,
          "text": text,
          "time": now,
          "user_id": user_id # Добавляем ID пользователя в сообщение
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
    
    # Информация о пользователе
    c.execute("SELECT id, username, nickname, avatar, theme FROM users WHERE id=%s", (user_id,))
    user = c.fetchone()
    if not user:
        db.close()
        return "User not found", 404
    
    u_id, u_username, u_nickname, u_avatar, u_theme = user
    colors = THEMES.get(u_theme, THEMES["matrix"])
    
    # Статистика
    c.execute("SELECT COUNT(*) FROM messages WHERE user_id=%s", (user_id,))
    msg_count = c.fetchone()[0]
    
    # Друзья
    c.execute("""
      SELECT u.id, u.username, u.nickname, u.avatar 
      FROM friendships f 
      JOIN users u ON f.friend_id = u.id 
      WHERE f.user_id = %s
    """, (user_id,))
    friends = c.fetchall()
    
    # Проверка статуса дружбы для текущего пользователя
    is_friend = False
    pending = False # Можно добавить логику заявок, пока просто друзья
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

    return f"""
    <body style="margin:0;background:{colors[0]};color:{colors[1]};font-family:Courier New">
    <div style="padding:20px">
      <a href="/chat">Back to Chat</a>
      <hr>
      <center>
        <img src="/static/avatars/{u_avatar}" width=100 style="border-radius:50%; border: 4px solid {colors[1]}">
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
        pass # Already friends
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
        
        # Обработка загруженного файла аватарки
        if 'avatar_file' in request.files:
            file = request.files['avatar_file']
            if file and file.filename != '':
                ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else 'png'
                new_filename = f"u{session['user_id']}_{uuid.uuid4().hex[:8]}.{ext}"
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], new_filename)
                file.save(filepath)
                avatar = new_filename
        
        c.execute("""
        UPDATE users SET nickname=%s,avatar=%s,theme=%s,timezone=%s
        WHERE id=%s
        """,(
          request.form["nickname"],
          avatar,
          request.form["theme"],
          request.form["timezone"],
          session["user_id"]
        ))
        db.commit()
        db.close()
        return redirect("/chat")

    c.execute("SELECT nickname,avatar,theme,timezone FROM users WHERE id=%s",(session["user_id"],))
    u=c.fetchone()
    db.close()
    
    # Список доступных тем и часовых поясов
    theme_options = "".join([f'<option value="{t}"{" selected" if t == u[2] else ""}>{t.title()}</option>' for t in THEMES.keys()])
    tz_list = sorted(list(available_timezones()))
    tz_options = "".join([f'<option value="{tz}"{" selected" if tz == u[3] else ""}>{tz}</option>' for tz in tz_list])

    return f"""
    <body style="background:#000;color:#0f0;font-family:Courier New">
    <h3>Settings</h3>
    <form method=post enctype="multipart/form-data">
      Nick:<input name=nickname value="{u[0]}"><br>
      Upload Avatar: <input type=file name=avatar_file accept="image/*"><br>
      Current Avatar: <img src="/static/avatars/{u[1]}" width=50><br>
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
