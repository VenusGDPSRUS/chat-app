import os, uuid, re
from datetime import datetime, timedelta
from flask import (
    Flask, request, session, redirect,
    render_template_string, send_from_directory, g
)
from flask_socketio import SocketIO, emit
from werkzeug.security import generate_password_hash, check_password_hash
from authlib.integrations.flask_client import OAuth
import psycopg
from psycopg.rows import dict_row

# ================= CONFIG =================
DATABASE_URL = os.environ["DATABASE_URL"]

MODERATORS = {"mahjong", "Admin123", "trollface69", "coaldev"}

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

# ================= APP =================
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev")

socketio = SocketIO(
    app,
    async_mode="threading",
    cors_allowed_origins="*",
    transports=["polling", "websocket"],
    manage_session=True
)

oauth = OAuth(app)
oauth.register(
    name="google",
    client_id=os.environ.get("GOOGLE_CLIENT_ID"),
    client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)

# ================= DB =================
def get_db():
    if "db" not in g:
        g.db = psycopg.connect(
            DATABASE_URL,
            row_factory=dict_row,
            autocommit=True
        )
    return g.db

@app.teardown_appcontext
def close_db(_):
    db = g.pop("db", None)
    if db:
        db.close()

def init_db():
    db = psycopg.connect(DATABASE_URL)
    c = db.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS users(
        id SERIAL PRIMARY KEY,
        nickname TEXT UNIQUE,
        username TEXT UNIQUE,
        password TEXT,
        google_id TEXT UNIQUE,
        avatar TEXT,
        theme TEXT,
        timezone TEXT,
        ip TEXT,
        banned BOOLEAN DEFAULT FALSE,
        ban_count INT DEFAULT 0,
        created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS messages(
        id UUID PRIMARY KEY,
        user_id INT REFERENCES users(id),
        text TEXT,
        created_at TEXT,
        deleted BOOLEAN DEFAULT FALSE
    );
    CREATE TABLE IF NOT EXISTS ip_bans(ip TEXT PRIMARY KEY);
    """)
    db.commit()
    db.close()

init_db()

# ================= HELPERS =================
from datetime import datetime, UTC

def now():
    return datetime.now(UTC).isoformat()

def valid_username(u):
    return re.fullmatch(r"[a-zA-Z0-9_]{3,20}", u)

def format_time(ts, tz):
    offsets = {"UTC":0,"UTC-8":-8,"UTC+3":3,"UTC+4":4}
    d = datetime.fromisoformat(ts) + timedelta(hours=offsets.get(tz,0))
    return d.strftime("%d/%m/%Y %H:%M:%S")

def user_tags(u):
    db = get_db()
    c = db.cursor()
    c.execute("SELECT COUNT(*) FROM messages WHERE user_id=%s", (u["id"],))
    cnt = c.fetchone()["count"]

    tags=[]
    if cnt >= 1000: tags.append(("Neighbor","#aaa"))
    elif cnt >= 500: tags.append(("Roulette","#6cf"))
    elif cnt >= 250: tags.append(("Worker","#6f6"))
    elif cnt >= 50: tags.append(("Stranger","#ccc"))

    if u["ban_count"] >= 2: tags.append(("Shell","#c7a15b"))
    elif u["ban_count"] >= 1: tags.append(("Crowded","#044569"))

    if u["nickname"] in MODERATORS:
        tags.append(("Admin","#f55"))

    return tags

# ================= AUTH =================
@app.route("/", methods=["GET","POST"])
def login():
    db = get_db()
    c = db.cursor()

    if request.method == "POST":
        ident = request.form["nickname"]
        c.execute(
            "SELECT * FROM users WHERE nickname=%s OR username=%s",
            (ident, ident)
        )
        u = c.fetchone()

        if not u or u["banned"]:
            return "Banned or not found"

        if u["password"] and check_password_hash(u["password"], request.form["password"]):
            session["uid"] = u["id"]
            return redirect("/chat")

        return "Wrong password"

    return """
    <h2>Login</h2>
    <form method=post>
      <input name=nickname placeholder="Nickname or username">
      <input type=password name=password placeholder=Password>
      <button>Login</button>
    </form>
    <a href=/register>Register</a><br><br>
    <a href=/auth/google>Login with Google</a>
    """

@app.route("/register", methods=["GET","POST"])
def register():
    db = get_db()
    c = db.cursor()

    if request.method == "POST":
        nick = request.form["nickname"]
        uname = request.form["username"]
        pwd = request.form["password"]

        if not valid_username(uname):
            return "Invalid username"

        try:
            c.execute("""
            INSERT INTO users
            (nickname,username,password,theme,timezone,ip,created_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
            """, (
                nick, uname, generate_password_hash(pwd),
                "crowdcontrol", "UTC",
                request.remote_addr, now()
            ))
            db.commit()
        except:
            return "Nickname or username exists"

        return redirect("/")

    return """
    <h2>Register</h2>
    <form method=post>
      <input name=nickname placeholder=Nickname>
      <input name=username placeholder=Username>
      <input type=password name=password placeholder=Password>
      <button>Register</button>
    </form>
    """

# ================= GOOGLE AUTH =================
@app.route("/auth/google")
def google_login():
    return oauth.google.authorize_redirect(
        os.environ["GOOGLE_REDIRECT_URL"]
    )

@app.route("/auth/google/callback")
def google_callback():
    token = oauth.google.authorize_access_token()
    info = token["userinfo"]

    db = get_db()
    c = db.cursor()

    c.execute("SELECT * FROM users WHERE google_id=%s", (info["sub"],))
    u = c.fetchone()

    if not u:
        uname = info["email"].split("@")[0]
        c.execute("""
        INSERT INTO users
        (nickname,username,google_id,theme,timezone,ip,created_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s)
        """, (
            info["name"], uname, info["sub"],
            "crowdcontrol", "UTC",
            request.remote_addr, now()
        ))
        db.commit()
        c.execute("SELECT * FROM users WHERE google_id=%s", (info["sub"],))
        u = c.fetchone()

    session["uid"] = u["id"]
    return redirect("/chat")

# ================= CHAT =================
@app.route("/chat")
def chat():
    if "uid" not in session:
        return redirect("/")
    db = get_db()
    c = db.cursor()
    c.execute("SELECT * FROM users WHERE id=%s", (session["uid"],))
    u = c.fetchone()
    bg, fg = THEMES.get(u["theme"], THEMES["dark"])
    return render_template_string(CHAT_HTML, bg=bg, fg=fg, nick=u["nickname"])

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# ================= SOCKET =================
@socketio.on("connect")
def on_connect():
    if "uid" not in session:
        return
    db = get_db()
    c = db.cursor()
    c.execute("""
    SELECT m.id,m.text,m.created_at,u.nickname,u.username
    FROM messages m JOIN users u ON m.user_id=u.id
    WHERE m.deleted=FALSE
    ORDER BY m.created_at
    """)
    rows = c.fetchall()

    out=[]
    for r in rows:
        out.append({
            "id": str(r["id"]),
            "name": r["nickname"],
            "username": r["username"],
            "time": r["created_at"],
            "msg": r["text"],
            "tags": []
        })
    emit("history", out)

@socketio.on("message")
def on_message(d):
    db = get_db()
    c = db.cursor()
    c.execute("SELECT * FROM users WHERE id=%s", (session["uid"],))
    u = c.fetchone()

    mid = uuid.uuid4()
    c.execute(
        "INSERT INTO messages VALUES (%s,%s,%s,%s,FALSE)",
        (mid, u["id"], d["msg"], now())
    )
    db.commit()

    emit("message",{
        "id": str(mid),
        "name": u["nickname"],
        "username": u["username"],
        "time": now(),
        "msg": d["msg"],
        "tags": []
    }, broadcast=True)

# ================= HTML =================
CHAT_HTML = """
<!doctype html>
<html>
<head>
<meta name=viewport content="width=device-width,initial-scale=1">
<script src="https://cdn.socket.io/4.7.5/socket.io.min.js"></script>
<style>
body{
  margin:0;
  background:{{bg}};
  color:{{fg}};
  font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;
}
#chat{padding:12px}
.message{
  display:grid;
  grid-template-columns:120px 1fr;
  gap:10px;
  margin-bottom:8px;
}
.time{font-size:11px;opacity:.7}
input,button{font-size:14px}
</style>
</head>
<body>
<h3 style="padding:10px">{{nick}}</h3>
<div id=chat></div>
<input id=msg style="width:80%" onkeydown="if(event.key=='Enter')send()">
<button onclick=send()>Send</button>
<script>
const s=io({transports:["polling","websocket"]});
function row(m){
 return `<div class=message>
 <div class=time>${m.time}</div>
 <div><b>${m.name}</b> @${m.username}<br>${m.msg}</div>
 </div>`;
}
s.on("history",d=>{chat.innerHTML="";d.forEach(m=>chat.innerHTML+=row(m));});
s.on("message",m=>chat.innerHTML+=row(m));
function send(){if(msg.value.trim())s.emit("message",{msg:msg.value});msg.value="";}
</script>
</body>
</html>
"""

# ================= RUN =================
if __name__ == "__main__":
    socketio.run(
        app,
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        allow_unsafe_werkzeug=True
    )
