import os, sqlite3, uuid, re
from datetime import datetime, timedelta
from flask import (
    Flask, request, session, redirect,
    render_template_string, send_from_directory, g
)
from flask_socketio import SocketIO, emit
from werkzeug.security import generate_password_hash, check_password_hash

# ================= CONFIG =================
DATA_DIR = "/data"
os.makedirs(DATA_DIR, exist_ok=True)
AVATARS = os.path.join(DATA_DIR, "avatars")
os.makedirs(AVATARS, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "app.db")

MODERATORS = {"mahjong", "Admin123", "trollface69", "coaldev"}

THEMES = {
    "dark": ("#111", "#fff"),
    "light": ("#eee", "#000"),
    "dracula": ("#282a36", "#f8f8f2"),
    "ocean": ("#002", "#0ff"),
    "crowdcontrol": ("#1c4975", "#112336"),
    "aero": ("#80f6ff", "#003b44"),
    "candy": ("#ff80b3", "#4a001f"),
}

# ================= APP =================
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "supersecretkey")

socketio = SocketIO(
    app,
    async_mode="threading",
    cors_allowed_origins="*",
    transports=["polling", "websocket"],
    manage_session=True
)

# ================= DB =================
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH, check_same_thread=False)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(_):
    db = g.pop("db", None)
    if db:
        db.close()

def init_db():
    db = sqlite3.connect(DB_PATH)
    c = db.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nickname TEXT UNIQUE,
        username TEXT UNIQUE,
        password TEXT,
        avatar TEXT,
        theme TEXT,
        timezone TEXT,
        ip TEXT,
        banned INTEGER DEFAULT 0,
        ban_count INTEGER DEFAULT 0,
        created_at TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS messages(
        id TEXT PRIMARY KEY,
        user_id INTEGER,
        text TEXT,
        created_at TEXT,
        deleted INTEGER DEFAULT 0
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS ip_bans(
        ip TEXT PRIMARY KEY
    )""")
    db.commit()
    db.close()

init_db()

# ================= HELPERS =================
def now():
    return datetime.utcnow().isoformat()

def valid_username(u):
    return re.fullmatch(r"[a-zA-Z0-9_]{3,20}", u)

def format_time(ts, tz):
    offsets = {"UTC":0,"UTC-8":-8,"UTC+3":3,"UTC+4":4}
    d = datetime.fromisoformat(ts) + timedelta(hours=offsets.get(tz,0))
    return d.strftime("%d/%m/%Y %H:%M:%S")

def user_tags(u):
    db = get_db()
    tags = []
    msg_count = db.execute(
        "SELECT COUNT(*) FROM messages WHERE user_id=?",
        (u["id"],)
    ).fetchone()[0]

    if msg_count >= 1000: tags.append(("Neighbor","#aaa"))
    elif msg_count >= 500: tags.append(("Roulette","#6cf"))
    elif msg_count >= 250: tags.append(("Worker","#6f6"))
    elif msg_count >= 50: tags.append(("Stranger","#ccc"))

    if u["ban_count"] >= 2: tags.append(("Shell","#c7a15b"))
    elif u["ban_count"] >= 1: tags.append(("Crowded","#044569"))

    if u["nickname"] in MODERATORS:
        tags.append(("Admin","#f55"))

    return tags

# ================= AUTH =================
@app.route("/", methods=["GET","POST"])
def login():
    db = get_db()
    if request.method == "POST":
        u = db.execute(
            "SELECT * FROM users WHERE nickname=?",
            (request.form["nickname"],)
        ).fetchone()

        if not u or u["banned"]:
            return "Banned or not found"

        if db.execute(
            "SELECT 1 FROM ip_bans WHERE ip=?",
            (request.remote_addr,)
        ).fetchone():
            return "IP banned"

        if check_password_hash(u["password"], request.form["password"]):
            session["uid"] = u["id"]
            return redirect("/chat")

        return "Wrong password"

    return """
    <h2>Login</h2>
    <form method=post>
    <input name=nickname placeholder=Nickname>
    <input type=password name=password placeholder=Password>
    <button>Login</button>
    </form>
    <a href=/register>Register</a>
    """

@app.route("/register", methods=["GET","POST"])
def register():
    db = get_db()
    if request.method == "POST":
        nick = request.form["nickname"]
        uname = request.form["username"]
        pwd = request.form["password"]

        if not valid_username(uname):
            return "Username: latin, numbers, _ only"

        avatar = request.files.get("avatar")
        fname = None
        if avatar and avatar.filename:
            fname = f"{uuid.uuid4()}.png"
            avatar.save(os.path.join(AVATARS, fname))

        try:
            db.execute("""INSERT INTO users
            (nickname,username,password,avatar,theme,timezone,ip,created_at)
            VALUES (?,?,?,?,?,?,?,?)""",
            (nick, uname, generate_password_hash(pwd),
             fname, "dark", "UTC", request.remote_addr, now()))
            db.commit()
        except:
            return "Nickname or username exists"

        return redirect("/")

    return """
    <h2>Register</h2>
    <form method=post enctype=multipart/form-data>
    <input name=nickname placeholder=Nickname>
    <input name=username placeholder=@username>
    <input type=password name=password placeholder=Password>
    <input type=file name=avatar>
    <button>Register</button>
    </form>
    """

# ================= CHAT =================
@app.route("/chat")
def chat():
    if "uid" not in session:
        return redirect("/")
    db = get_db()
    u = db.execute("SELECT * FROM users WHERE id=?", (session["uid"],)).fetchone()
    bg, fg = THEMES.get(u["theme"], THEMES["dark"])
    return render_template_string(CHAT_HTML, bg=bg, fg=fg, nick=u["nickname"])

@app.route("/avatars/<f>")
def avatar(f):
    return send_from_directory(AVATARS, f)

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
    u = db.execute("SELECT * FROM users WHERE id=?", (session["uid"],)).fetchone()

    rows = db.execute("""
    SELECT m.id,m.text,m.created_at,u.nickname,u.username,u.avatar
    FROM messages m JOIN users u ON m.user_id=u.id
    WHERE m.deleted=0
    """).fetchall()

    out=[]
    for r in rows:
        tags = user_tags(
            db.execute("SELECT * FROM users WHERE nickname=?", (r["nickname"],)).fetchone()
        )
        out.append({
            "id": r["id"],
            "name": r["nickname"],
            "username": r["username"],
            "avatar": r["avatar"],
            "time": format_time(r["created_at"], u["timezone"]),
            "msg": r["text"],
            "tags": tags
        })
    emit("history", out)

@socketio.on("message")
def on_message(d):
    db = get_db()
    uid = session["uid"]
    u = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    text = d["msg"].strip()

    if text.startswith("/") and u["nickname"] in MODERATORS:
        cmd = text.split()
        if cmd[0]=="/clear":
            db.execute("DELETE FROM messages")
        elif cmd[0]=="/ban" and len(cmd)>1:
            db.execute("UPDATE users SET banned=1,ban_count=ban_count+1 WHERE nickname=?", (cmd[1],))
        elif cmd[0]=="/unban" and len(cmd)>1:
            db.execute("UPDATE users SET banned=0 WHERE nickname=?", (cmd[1],))
        elif cmd[0]=="/ipban" and len(cmd)>1:
            ip = db.execute("SELECT ip FROM users WHERE nickname=?", (cmd[1],)).fetchone()
            if ip:
                db.execute("INSERT OR IGNORE INTO ip_bans VALUES (?)", (ip["ip"],))
        db.commit()
        return

    mid = str(uuid.uuid4())
    db.execute(
        "INSERT INTO messages VALUES (?,?,?,?,0)",
        (mid, uid, text, now())
    )
    db.commit()

    emit("message",{
        "id": mid,
        "name": u["nickname"],
        "username": u["username"],
        "avatar": u["avatar"],
        "time": format_time(now(), u["timezone"]),
        "msg": text,
        "tags": user_tags(u)
    }, broadcast=True)

# ================= HTML =================
CHAT_HTML = """
<!doctype html>
<html>
<head>
<meta name=viewport content="width=device-width,initial-scale=1">
<script src="https://cdn.socket.io/4.7.5/socket.io.min.js"></script>
<style>
body{margin:0;background:{{bg}};color:{{fg}};font-family:system-ui}
.message{display:grid;grid-template-columns:110px 40px 1fr;gap:8px}
.time{font-size:11px;opacity:.6}
.avatar{width:32px;height:32px;border-radius:50%}
.tag{font-size:11px;margin-right:4px}
.username{font-size:11px;opacity:.6}
</style>
</head>
<body>
<h3>{{nick}}</h3>
<a href=/logout>Logout</a>
<div id=chat></div>
<input id=msg onkeydown="if(event.key=='Enter')send()">
<button onclick=send()>Send</button>
<script>
const s = io({ transports: ["polling", "websocket"] });
function row(m){
 let t=m.tags.map(x=>`<span class=tag style=color:${x[1]}>[${x[0]}]</span>`).join("");
 return `<div class=message>
 <div class=time>${m.time.replace(" ","<br>")}</div>
 <img class=avatar src=/avatars/${m.avatar}>
 <div><b>${m.name}</b> ${t}<span class=username>@${m.username}</span><br>${m.msg}</div>
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
