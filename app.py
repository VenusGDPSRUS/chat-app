# app.py

import os
import psycopg
from flask import Flask, request, session, redirect
from flask_socketio import SocketIO, emit, disconnect
from datetime import datetime
from zoneinfo import ZoneInfo

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev")

# Важно: manage_session=False для корректной работы сессии Flask
socketio = SocketIO(app, async_mode="threading", manage_session=False)

DATABASE_URL = os.environ.get("DATABASE_URL")

# ---------- DB ----------

def get_db():
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
      id SERIAL PRIMARY KEY,
      user_id INTEGER REFERENCES users(id),
      friend_id INTEGER REFERENCES users(id),
      UNIQUE(user_id, friend_id)
    )
    """)

    db.commit()
    db.close()
init_db()

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
    "contrast_light": ("#ffffff", "#cc1623"),
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
            # Сначала получаем максимальный ID для присвоения нового порядкового номера
            c.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM users")
            new_id = c.fetchone()[0]
            
            c.execute(
              "INSERT INTO users(id,username,password,avatar,nickname) VALUES(%s,%s,%s,%s,%s)",
              (
                new_id,
                request.form["username"],
                request.form["password"],
                request.form.get("avatar","a1.png"),
                request.form["username"]
              )            )
            db.commit()
        except psycopg.IntegrityError:
             # Обработка случая, когда имя пользователя уже существует
             db.close()
             return "Username already exists!", 400
        db.close()
        return redirect("/")
    return """
    <body style="background:#000;color:#0f0;font-family:Courier New">
    <h3>Register</h3>
    <form method=post>
      <input name=username placeholder=username><br>
      <input name=password type=password placeholder=password><br>
      <input type=hidden name=avatar id=avatar>
      <img src=/static/avatars/a1.png onclick="pick('a1.png')">
      <img src=/static/avatars/a2.png onclick="pick('a2.png')">
      <img src=/static/avatars/a3.png onclick="pick('a3.png')"><br>
      <button>Register</button>
    </form>
    <script>
      function pick(a){avatar.value=a;}
    </script>
    """

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# --- Сохранение сессии пользователя для сокета ---
# Глобальный словарь для хранения user_id по sid сокета
connected_users = {}

@socketio.on('connect')
def handle_connect():
    user_id = session.get('user_id')
    if user_id is None:
        print(f"Socket connection rejected: No user_id in session for SID {request.sid}")
        disconnect() # Отключаем незалогиненного пользователя
        return False
    else:
        connected_users[request.sid] = user_id
        print(f"User {user_id} connected with SID {request.sid}")
        # Не эмитим ничего здесь, просто подтверждение подключения сервером

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    if sid in connected_users:
        user_id = connected_users.pop(sid)
        print(f"User {user_id} disconnected, SID {sid}")


# ---------- PROFILE ----------

@app.route("/profile/<int:user_id>")
def profile(user_id):
    db = get_db()
    c = db.cursor()
    
    # Получаем данные профиля
    c.execute("SELECT id, username, nickname, avatar, theme, timezone FROM users WHERE id=%s", (user_id,))
    user_data = c.fetchone()
    
    if not user_data:
        db.close()
        return "<body style='background:#000;color:#f00;font-family:Courier New'>User not found<a href=/chat>back</a></body>"
    
    uid, username, nickname, avatar, theme, tz = user_data
    
    # Получаем список друзей
    c.execute("""
        SELECT u.id, u.username, u.nickname, u.avatar 
        FROM friendships f 
        JOIN users u ON f.friend_id = u.id 
        WHERE f.user_id = %s
    """, (user_id,))
    friends = c.fetchall()
    
    # Проверяем, является ли этот пользователь другом текущего пользователя
    current_user_id = session.get('user_id')
    is_friend = False
    is_self = False
    
    if current_user_id:
        if current_user_id == user_id:
            is_self = True
        else:
            c.execute("SELECT 1 FROM friendships WHERE user_id=%s AND friend_id=%s", (current_user_id, user_id))
            is_friend = c.fetchone() is not None
    
    db.close()
    
    colors = THEMES.get(theme, THEMES["matrix"])
    
    friends_html = ""
    for fid, fusername, fnick, favatar in friends:
        friends_html += f'<div style="display:flex;align-items:center;margin:5px;"><img src="/static/avatars/{favatar}" width=32> <a href="/profile/{fid}" style="color:{colors[1]}">{fnick}</a> (ID: {fid})</div>'
    
    action_button = ""
    if not is_self and current_user_id and not is_friend:
        action_button = f'<a href="/add_friend/{user_id}" style="color:#0f0">[Add as Friend]</a> '
    elif not is_self and current_user_id and is_friend:
        action_button = f'<a href="/remove_friend/{user_id}" style="color:#f00">[Remove Friend]</a> '
    
    return f"""
    <body style="margin:0;background:{colors[0]};color:{colors[1]};font-family:Courier New">
    <div style="padding:10px;border-bottom:1px solid {colors[1]}">
      <a href=/chat>Back to Chat</a>
      <a href=/leaderboard>Leaderboard</a>
    </div>
    <div style="padding:20px">
      <img src="/static/avatars/{avatar}" width=64><br>
      <h2>{nickname}</h2>
      <p>Username: {username}</p>
      <p>ID: {uid}</p>
      <p>Timezone: {tz}</p>
      <p>{action_button}</p>
      <h3>Friends ({len(friends)}):</h3>
      {friends_html if friends_html else '<p>No friends yet</p>'}
    </div>
    </body>
    """

@app.route("/add_friend/<int:friend_id>")
def add_friend(friend_id):
    if "user_id" not in session:
        return redirect("/")
    
    current_user_id = session["user_id"]
    
    if current_user_id == friend_id:
        return redirect(f"/profile/{friend_id}")
    
    db = get_db()
    c = db.cursor()
    try:
        c.execute("INSERT INTO friendships(user_id, friend_id) VALUES(%s, %s)", (current_user_id, friend_id))
        db.commit()
    except psycopg.IntegrityError:
        pass  # Уже друзья
    finally:
        db.close()
    
    return redirect(f"/profile/{friend_id}")

@app.route("/remove_friend/<int:friend_id>")
def remove_friend(friend_id):
    if "user_id" not in session:
        return redirect("/")
    
    current_user_id = session["user_id"]
    
    db = get_db()
    c = db.cursor()
    c.execute("DELETE FROM friendships WHERE user_id=%s AND friend_id=%s", (current_user_id, friend_id))
    db.commit()
    db.close()
    
    return redirect(f"/profile/{friend_id}")


# ---------- CHAT ----------

@app.route("/chat")
def chat():
    if "user_id" not in session:
        return redirect("/")

    db=get_db(); c=db.cursor()
    c.execute("SELECT nickname,avatar,theme,timezone FROM users WHERE id=%s",(session["user_id"],))
    nick,avatar,theme,tz=c.fetchone()
    colors=THEMES.get(theme,THEMES["matrix"])
    
    # Получаем список друзей текущего пользователя
    c.execute("""
        SELECT friend_id FROM friendships WHERE user_id = %s
    """, (session["user_id"],))
    friend_ids = [row[0] for row in c.fetchall()]
    db.close()

    return f"""
<!doctype html>
<body style="margin:0;background:{colors[0]};color:{colors[1]};font-family:Courier New"> <!-- Исправлено: индексы [0], [1] -->
<div style="padding:10px;border-bottom:1px solid {colors[1]}">
  {nick}
  <a href=/settings>Settings</a>
  <a href=/leaderboard>Leaderboard</a>
  <a href=/logout>Logout</a>
</div>

<div id=chat style="height:70vh;overflow:auto;padding:10px"></div>

<div style="display:flex">
  <input id=msg style="flex:1">
  <button onclick=send()>Send</button>
</div>

<script src="https://cdn.socket.io/4.7.2/socket.io.min.js"></script>
<script>
let s=io(); // Подключаемся к текущему домену/порту
// Передаем список ID друзей на клиент
const friendIds = {friend_ids};
s.on("connect", () => {{
    console.log("Connected to server via Socket.IO");
}});
s.on("msg",m=>{{
  const isFriend = friendIds.includes(m.user_id);
  const highlightStyle = isFriend ? 'border-left: 3px solid #0f0; background: rgba(0,255,0,0.1);' : '';
  chat.innerHTML+=`
  <div style="padding:5px;margin:5px 0;{highlightStyle}">
    <img src="/static/avatars/${{m.avatar}}" width=32>
    <b><a href="/profile/${{m.user_id}}" style="color:{colors[1]}">${{m.nick}}</a></b>
    <small>[ID: ${{m.user_id}}] ${{m.time}}</small><br>
    ${{m.text}}
  </div>`;
  chat.scrollTop=chat.scrollHeight;
}});function send(){{
  const text = msg.value.trim();
  if (text) {{ // Проверяем, что сообщение не пустое
    s.emit("msg", text);
    msg.value=""; // Очищаем после отправки
  }}
}}
</script>
</body>
"""

# ---------- SOCKET (обработка сообщений) ----------

@socketio.on("msg")
def msg(text):
    # Получаем user_id из глобального словаря, используя SID сокета
    user_id = connected_users.get(request.sid)
    if user_id is None:
        print(f"Message received from unknown SID {request.sid}, ignoring.")
        return # Или вызвать disconnect(), если хотите жестко отключить

    db = None
    try:
        db = get_db()
        c = db.cursor()
        # Запрашиваем данные пользователя по user_id из БД
        c.execute("""
          SELECT nickname, avatar, theme, timezone
          FROM users WHERE id=%s
        """, (user_id,))
        user_data = c.fetchone()

        if not user_data:
            print(f"User data not found for ID {user_id}, SID {request.sid}, ignoring message.")
            return # Или вызвать disconnect()

        nick, avatar, theme, tz = user_data

        # Вставляем сообщение в БД
        c.execute("INSERT INTO messages(user_id,content) VALUES(%s,%s)", (user_id, text))
        db.commit()

        # Форматируем время
        now = datetime.now(ZoneInfo(tz)).strftime("%H:%M:%S")

        # Отправляем сообщение всем (broadcast=True)
        emit("msg",{
          "nick": nick,
          "avatar": avatar,
          "text": text,
          "time": now,
          "user_id": user_id
        }, broadcast=True)

    except Exception as e:
        print(f"Error processing message for user {user_id}, SID {request.sid}: {e}")
        # Опционально: эмитить ошибку обратно пользователю
        # emit("error", {"message": "Failed to send message"})
    finally:
        if db:
            db.close()


# ---------- SETTINGS ----------

@app.route("/settings", methods=["GET","POST"])
def settings():
    if "user_id" not in session:
        return redirect("/")
    
    db=get_db(); c=db.cursor()
    if request.method=="POST":
        c.execute("""
        UPDATE users SET nickname=%s,avatar=%s,theme=%s,timezone=%s
        WHERE id=%s
        """,(
          request.form["nickname"],
          request.form["avatar"],
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

    return f"""
    <body style="background:#000;color:#0f0;font-family:Courier New">
    <h3>Settings</h3>
    <form method=post>
      Nick:<input name=nickname value="{u[0]}"><br>
      Avatar:<input name=avatar value="{u[1]}"><br>
      Theme:<input name=theme value="{u[2]}"><br>
      TZ:<input name=timezone value="{u[3]}"><br>
      <button>Save</button>
    </form>
    </body>    """

# ---------- LEADERBOARD ----------

@app.route("/leaderboard")
def leaderboard():
    db=get_db(); c=db.cursor()
    c.execute("""
    SELECT u.id, u.username, COUNT(m.id) as msg_count
    FROM users u LEFT JOIN messages m ON u.id=m.user_id
    GROUP BY u.id ORDER BY msg_count DESC
    """)
    rows=c.fetchall()
    db.close()
    out="<body style='background:#000;color:#0f0;font-family:Courier New'><h3>Leaderboard</h3>"
    for uid, u, cnt in rows:
        out+=f"<a href='/profile/{uid}' style='color:#0f0'>{u}</a> (ID: {uid}): {cnt}<br>"
    return out+"<a href=/chat>back</a></body>"

# ---------- RUN ----------

if __name__=="__main__":
    # Убедитесь, что используете порт, предоставленный Railway
    port = int(os.environ.get("PORT", 5000))
    print(f"Starting server on port {port}")
    socketio.run(app, host="0.0.0.0", port=port, debug=False) # debug=False для продакшена