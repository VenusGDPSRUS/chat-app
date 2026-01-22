import eventlet
eventlet.monkey_patch()

from flask import Flask, request, redirect, session, send_from_directory, render_template_string
from flask_socketio import SocketIO, emit
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import os, json, uuid, re

app = Flask(__name__)
app.secret_key = "supersecretkey"
socketio = SocketIO(app, cors_allowed_origins="*")

UPLOAD_FOLDER = "avatars"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

USERS_FILE = "users.json"
HISTORY_FILE = "chat_history.json"

moderators = {"mahjong", "Admin123", "trollface69", "coaldev"}

# ---------- helpers ----------
def load(path, default):
    if os.path.exists(path):
        return json.load(open(path, "r", encoding="utf-8"))
    return default

users = load(USERS_FILE, {})
history = load(HISTORY_FILE, [])

def save():
    json.dump(users, open(USERS_FILE,"w",encoding="utf-8"), ensure_ascii=False, indent=2)
    json.dump(history, open(HISTORY_FILE,"w",encoding="utf-8"), ensure_ascii=False, indent=2)

def format_time(iso, tz):
    t = datetime.fromisoformat(iso)
    offsets = {"UTC":0,"UTC-8":-8,"UTC+3":3,"UTC+4":4}
    t += timedelta(hours=offsets.get(tz,0))
    return t.strftime("%d/%m/%Y %H:%M:%S")

def highlight_mentions(text):
    for u in users.values():
        text = re.sub(rf"@{u['username']}\b",
                      f'<span class="mention">@{u["username"]}</span>',
                      text)
    return text

# ---------- auth ----------
@app.route("/", methods=["GET","POST"])
def login():
    if request.method == "POST":
        u = request.form["nickname"]
        p = request.form["password"]
        if u in users and check_password_hash(users[u]["password"], p):
            session["user"] = u
            return redirect("/chat")
        return "Wrong login"

    return render_template_string(LOGIN_HTML)

@app.route("/register", methods=["GET","POST"])
def register():
    if request.method == "POST":
        nick = request.form["nickname"]
        uname = request.form["username"]
        p = request.form["password"]

        if " " in uname:
            return "Username cannot contain spaces"
        if nick in users:
            return "Nickname exists"
        for u in users.values():
            if u["username"] == uname:
                return "Username taken"

        f = request.files["avatar"]
        fname = f"{nick}.png"
        f.save(os.path.join(UPLOAD_FOLDER, fname))

        users[nick] = {
            "password": generate_password_hash(p),
            "avatar": fname,
            "username": uname,
            "theme": "dark",
            "timezone": "UTC",
            "last_nick": None
        }
        save()
        session["user"] = nick
        return redirect("/chat")

    return render_template_string(REGISTER_HTML)

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# ---------- settings ----------
@app.route("/settings", methods=["GET","POST"])
def settings():
    if "user" not in session:
        return redirect("/")
    u = session["user"]
    user = users[u]

    if request.method == "POST":
        if "newname" in request.form:
            now = datetime.utcnow()
            if user["last_nick"]:
                if now - datetime.fromisoformat(user["last_nick"]) < timedelta(days=3):
                    return "Nick cooldown (3 days)"
            new = request.form["newname"]
            users[new] = users.pop(u)
            users[new]["last_nick"] = now.isoformat()
            session["user"] = new

        if "theme" in request.form:
            user["theme"] = request.form["theme"]
        if "tz" in request.form:
            user["timezone"] = request.form["tz"]
        if "avatar" in request.files:
            request.files["avatar"].save(os.path.join(UPLOAD_FOLDER, user["avatar"]))

        save()

    return render_template_string(SETTINGS_HTML)

# ---------- chat ----------
@app.route("/chat")
def chat():
    if "user" not in session:
        return redirect("/")
    u = session["user"]
    return render_template_string(CHAT_HTML, user=u, theme=users[u]["theme"])

@app.route("/avatars/<f>")
def avatar(f):
    return send_from_directory(UPLOAD_FOLDER, f)

# ---------- socket ----------
@socketio.on("connect")
def connect():
    if "user" not in session:
        return
    u = session["user"]
    tz = users[u]["timezone"]
    out = []
    for m in history:
        mm = m.copy()
        mm["time"] = format_time(m["raw"], tz)
        mm["can_delete"] = (m["name"] == u)
        mm["is_admin"] = (m["name"] in moderators)
        out.append(mm)
    emit("history", out)

@socketio.on("message")
def message(data):
    if "user" not in session:
        return
    u = session["user"]
    now = datetime.utcnow()

    msg = {
        "id": str(uuid.uuid4()),
        "name": u,
        "username": users[u]["username"],
        "avatar": users[u]["avatar"],
        "raw": now.isoformat(),
        "msg": highlight_mentions(data["msg"]),
    }
    history.append(msg)
    save()

    msg["time"] = format_time(msg["raw"], users[u]["timezone"])
    msg["can_delete"] = True
    msg["is_admin"] = (u in moderators)

    emit("message", msg, broadcast=True)

@socketio.on("delete")
def delete(data):
    if "user" not in session:
        return
    u = session["user"]
    for m in history:
        if m["id"] == data["id"] and m["name"] == u:
            m["msg"] = "(deleted)"
            save()
            emit("delete", {"id": data["id"]}, broadcast=True)

# ---------- HTML ----------
LOGIN_HTML = """<!DOCTYPE html><html><head><title>Login</title>""" + """
<style>""" + """
""" + """</style></head><body>
<div class="card">
<h2>Welcome</h2>
<form method="POST">
<input name="nickname" placeholder="Nickname">
<input type="password" name="password" placeholder="Password">
<button>Login</button>
</form>
<div class="link"><a href="/register">Create account</a></div>
</div></body></html>"""

REGISTER_HTML = LOGIN_HTML.replace("Welcome","Register").replace("Login","Register").replace("/register","/")

SETTINGS_HTML = """
<h2>Settings</h2>
<form method="POST">
<input name="newname" placeholder="New nickname">
<button>Change Nick</button>
</form>
<form method="POST" enctype="multipart/form-data">
<input type="file" name="avatar">
<button>Avatar</button>
</form>
<form method="POST">
<select name="theme">
<option>dark</option><option>light</option><option>matrix</option>
<option>ocean</option><option>sunset</option><option>neon</option>
<option>retro</option><option>dracula</option>
</select>
<button>Theme</button>
</form>
<form method="POST">
<select name="tz">
<option>UTC</option><option>UTC-8</option><option>UTC+3</option><option>UTC+4</option>
</select>
<button>Timezone</button>
</form>
<a href="/chat">Back</a>
"""

CHAT_HTML = """<!DOCTYPE html>
<html>
<head>
<script src="https://cdn.socket.io/4.5.4/socket.io.min.js"></script>
<style>
body{font-family:Courier New;margin:0}
.dark{background:#111;color:white}
.light{background:#eee;color:black}
.matrix{background:black;color:#0f0}
.ocean{background:#002;color:#0ff}
.sunset{background:#300;color:#ff9}
.neon{background:#000;color:#f0f}
.retro{background:#210;color:#fc0}
.dracula{background:#2b2b2b;color:#ff79c6}

#chat{height:calc(100vh - 80px);overflow-y:auto;padding:10px}
.msg{display:flex;margin-bottom:14px}
.time{width:170px;opacity:.6}
.body{display:flex;gap:10px}
.avatar{width:36px;height:36px;border-radius:50%}
.header{display:flex;gap:6px;align-items:center}
.username{font-size:11px;opacity:.6}
.text{margin-top:2px}
.mention{color:#4da6ff;font-weight:bold}

.input-bar{display:flex;gap:6px;padding:8px;position:fixed;bottom:0;left:0;right:0;background:#000}
input{flex:1;padding:10px;border-radius:8px;border:none}
button{padding:10px;border-radius:8px;border:none}
@media(max-width:768px){
.msg{flex-direction:column}
.time{width:auto;font-size:11px}
}
</style>
</head>
<body class="{{theme}}">
<div id="chat"></div>
<div class="input-bar">
<input id="msg" onkeydown="if(event.key==='Enter')send()">
<button onclick="send()">Send</button>
</div>
<script>
const socket=io();
function html(m){
return `<div class="msg" id="m${m.id}">
<div class="time">[${m.time}]</div>
<div class="body">
<img class="avatar" src="/avatars/${m.avatar}">
<div>
<div class="header"><b>${m.name}</b><span class="username">@${m.username}</span></div>
<div class="text">${m.msg}</div>
</div></div></div>`}
socket.on("history",d=>{chat.innerHTML="";d.forEach(m=>chat.innerHTML+=html(m));chat.scrollTop=chat.scrollHeight})
socket.on("message",m=>{chat.innerHTML+=html(m);chat.scrollTop=chat.scrollHeight})
function send(){if(msg.value.trim()){socket.emit("message",{msg:msg.value});msg.value=""}}
</script>
</body>
</html>
"""

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host="0.0.0.0", port=port)
