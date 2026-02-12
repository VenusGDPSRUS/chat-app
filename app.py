import os
import psycopg
from flask import Flask, request, session, redirect
from flask_socketio import SocketIO, emit
from datetime import datetime
from zoneinfo import ZoneInfo

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY","dev")

socketio = SocketIO(app, async_mode="threading")

DATABASE_URL = os.environ.get("DATABASE_URL")

# ---------- DB ----------

def get_db():
    return psycopg.connect(DATABASE_URL)

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
            return redirect("/chat")
    return "<form method=post><input name=username><input name=password type=password><button>Login</button></form><a href=/register>Register</a>"

@app.route("/register", methods=["GET","POST"])
def register():
    if request.method=="POST":
        db=get_db(); c=db.cursor()
        c.execute(
          "INSERT INTO users(username,password,avatar,nickname) VALUES(%s,%s,%s,%s)",
          (
            request.form["username"],
            request.form["password"],
            request.form.get("avatar","a1.png"),
            request.form["username"]
          )
        )
        db.commit()
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

# ---------- CHAT ----------

@app.route("/chat")
def chat():
    if "user_id" not in session:
        return redirect("/")

    db=get_db(); c=db.cursor()
    c.execute("SELECT nickname,avatar,theme,timezone FROM users WHERE id=%s",(session["user_id"],))
    nick,avatar,theme,tz=c.fetchone()
    colors=THEMES.get(theme,THEMES["matrix"])

    return f"""
<!doctype html>
<body style="margin:0;background:{colors['bg']};color:{colors['fg']};font-family:Courier New">
<div style="padding:10px;border-bottom:1px solid {colors['fg']}">
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
let s=io();
s.on("msg",m=>{
  chat.innerHTML+=`
  <div>
    <img src="/static/avatars/${{m.avatar}}" width=32>
    <b>${{m.nick}}</b>
    <small>${{m.time}}</small><br>
    ${{m.text}}
  </div>`;
  chat.scrollTop=chat.scrollHeight;
});
function send(){
  s.emit("msg",msg.value);
  msg.value="";
}
</script>
</body>
"""

# ---------- SOCKET ----------

@socketio.on("msg")
def msg(text):
    db=get_db(); c=db.cursor()
    c.execute("""
      SELECT nickname,avatar,theme,timezone
      FROM users WHERE id=%s
    """,(session["user_id"],))
    nick,avatar,theme,tz=c.fetchone()

    c.execute("INSERT INTO messages(user_id,content) VALUES(%s,%s)",(session["user_id"],text))
    db.commit()

    now=datetime.now(ZoneInfo(tz)).strftime("%H:%M:%S")

    emit("msg",{
      "nick":nick,
      "avatar":avatar,
      "text":text,
      "time":now
    },broadcast=True)

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
        return redirect("/chat")

    c.execute("SELECT nickname,avatar,theme,timezone FROM users WHERE id=%s",(session["user_id"],))
    u=c.fetchone()

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
    </body>
    """

# ---------- LEADERBOARD ----------

@app.route("/leaderboard")
def leaderboard():
    db=get_db(); c=db.cursor()
    c.execute("""
    SELECT u.username,COUNT(m.id)
    FROM users u LEFT JOIN messages m ON u.id=m.user_id
    GROUP BY u.id ORDER BY 2 DESC
    """)
    rows=c.fetchall()
    out="<body style='background:#000;color:#0f0;font-family:Courier New'><h3>Leaderboard</h3>"
    for u,cnt in rows:
        out+=f"{u}: {cnt}<br>"
    return out+"<a href=/chat>back</a></body>"

# ---------- RUN ----------

if __name__=="__main__":
    socketio.run(app,host="0.0.0.0",port=5000)
