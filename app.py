from flask import Flask, request, redirect, session, send_from_directory, render_template_string
from flask_socketio import SocketIO, emit
from werkzeug.security import generate_password_hash, check_password_hash
from pyngrok import ngrok
from datetime import datetime, timedelta
import os, json, uuid, re

app = Flask(__name__)
app.secret_key = "supersecretkey"
socketio = SocketIO(app)

UPLOAD_FOLDER = "avatars"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

USERS_FILE = "users.json"
HISTORY_FILE = "chat_history.json"
IPBAN_FILE = "ip_bans.json"

moderators = {"mahjong", "Admin123", "trollface69", "coaldev"}

def load(file, default):
    if os.path.exists(file):
        return json.load(open(file,"r",encoding="utf-8"))
    return default

users = load(USERS_FILE, {})
history = load(HISTORY_FILE, [])
ip_bans = load(IPBAN_FILE, {})

def save():
    json.dump(users, open(USERS_FILE,"w",encoding="utf-8"), ensure_ascii=False, indent=2)
    json.dump(history, open(HISTORY_FILE,"w",encoding="utf-8"), ensure_ascii=False, indent=2)
    json.dump(ip_bans, open(IPBAN_FILE,"w",encoding="utf-8"), ensure_ascii=False, indent=2)

def format_time(iso, tz):
    t = datetime.fromisoformat(iso)
    offset = {"UTC":0,"UTC-8":-8,"UTC+3":3,"UTC+4":4}[tz]
    t += timedelta(hours=offset)
    return t.strftime("%Y-%m-%d %H:%M:%S")

def highlight_mentions(text):
    for u in users.values():
        uname = u["username"]
        text = re.sub(rf"@{uname}\b", f'<span class="mention">@{uname}</span>', text)
    return text

# ===== LOGIN =====
@app.route("/", methods=["GET","POST"])
def login():
    if request.method=="POST":
        u=request.form["username"]
        p=request.form["password"]
        ip=request.remote_addr

        if u in ip_bans and ip_bans[u]==ip:
            return "IP BANNED"

        if u in users and check_password_hash(users[u]["password"],p):
            session["user"]=u
            return redirect("/chat")
        return "Wrong login"

    return """
    <h2>Login</h2>
    <form method="POST">
      <input name="username"><br>
      <input type="password" name="password"><br>
      <button>Login</button>
    </form>
    <a href="/register">Register</a>
    """

# ===== REGISTER =====
@app.route("/register", methods=["GET","POST"])
def register():
    if request.method=="POST":
        nick=request.form["nickname"]
        uname=request.form["username"]
        p=request.form["password"]

        if " " in uname:
            return "Username cannot contain spaces"

        for u in users.values():
            if u["username"] == uname:
                return "Username already taken"

        if nick in users:
            return "Nickname already exists"

        f=request.files["avatar"]
        name=f"{nick}.png"
        f.save(os.path.join(UPLOAD_FOLDER,name))

        users[nick]={
            "password":generate_password_hash(p),
            "avatar":name,
            "theme":"dark",
            "timezone":"UTC",
            "last_nick":None,
            "username":uname
        }
        save()
        session["user"]=nick
        return redirect("/chat")

    return """
    <h2>Register</h2>
    <form method="POST" enctype="multipart/form-data">
      <input name="nickname" placeholder="Nickname"><br>
      <input name="username" placeholder="@username (no spaces)"><br>
      <input type="password" name="password"><br>
      <input type="file" name="avatar"><br>
      <button>Register</button>
    </form>
    """

# ===== SETTINGS =====
@app.route("/settings", methods=["GET","POST"])
def settings():
    u=session["user"]
    user=users[u]

    if request.method=="POST":
        if "newname" in request.form:
            now=datetime.utcnow()
            if user["last_nick"]:
                if now-datetime.fromisoformat(user["last_nick"]) < timedelta(days=3):
                    return "Nick change cooldown"

            new=request.form["newname"]
            users[new]=users.pop(u)
            users[new]["last_nick"]=now.isoformat()
            session["user"]=new
            save()
            return redirect("/settings")

        if "theme" in request.form:
            user["theme"]=request.form["theme"]

        if "tz" in request.form:
            user["timezone"]=request.form["tz"]

        if "avatar" in request.files:
            f=request.files["avatar"]
            f.save(os.path.join(UPLOAD_FOLDER,user["avatar"]))

        save()

    return """
    <h2>Settings</h2>
    <form method="POST">
      <input name="newname" placeholder="New nickname">
      <button>Change Nick</button>
    </form><br>

    <form method="POST" enctype="multipart/form-data">
      <input type="file" name="avatar">
      <button>Change Avatar</button>
    </form><br>

    <form method="POST">
      <select name="theme">
        <option>dark</option><option>light</option><option>matrix</option>
        <option>ocean</option><option>sunset</option><option>neon</option>
        <option>retro</option><option>dracula</option>
      </select>
      <button>Theme</button>
    </form><br>

    <form method="POST">
      <select name="tz">
        <option>UTC</option><option>UTC-8</option>
        <option>UTC+3</option><option>UTC+4</option>
      </select>
      <button>Timezone</button>
    </form>

    <br><a href="/chat">Back</a>
    """

# ===== CHAT =====
@app.route("/chat")
def chat():
    u=session["user"]
    return render_template_string("""
<!DOCTYPE html>
<html>
<head>
<script src="https://cdn.socket.io/4.5.4/socket.io.min.js"></script>
<style>
body{font-family:Courier New}
.dark{background:#111;color:white}
.light{background:#eee;color:black}
.matrix{background:black;color:#0f0}
.ocean{background:#002;color:#0ff}
.sunset{background:#300;color:#ff9}
.neon{background:#000;color:#f0f}
.retro{background:#210;color:#fc0}
.dracula{background:#2b2b2b;color:#ff79c6}

#chat{height:300px;overflow-y:scroll;border:1px solid #555;padding:5px}
.avatar{width:25px;border-radius:50%}
.username{font-size:11px;opacity:0.7}
.mention{font-weight:bold;color:#4da6ff}
</style>
</head>

<body class="{{theme}}">
<h3>{{user}}</h3>
<a href="/settings">Settings</a> | <a href="/logout">Logout</a>

<div id="chat"></div>

<input id="msg" onkeydown="if(event.key==='Enter')send()">
<button onclick="send()">Send</button>

<script>
const socket=io();

function msgHTML(m){
  let del=m.can_delete?`<button onclick="del('${m.id}')">🗑</button>`:"";
  return `<div id="m${m.id}">
    [${m.time}] <img class="avatar" src="/avatars/${m.avatar}">
    <b>${m.name}</b><div class="username">@${m.username}</div>
    ${m.msg} ${del}
  </div>`;
}

socket.on("history",d=>{
  chat.innerHTML="";
  d.forEach(m=>chat.innerHTML+=msgHTML(m));
});

socket.on("message",m=>{
  chat.innerHTML+=msgHTML(m);
});

socket.on("delete",d=>{
  document.getElementById("m"+d.id).innerHTML="(deleted)";
});

function send(){
  let t=msg.value.trim();
  if(!t) return;
  socket.emit("message",{msg:t});
  msg.value="";
}

function del(id){
  socket.emit("delete",{id:id});
}
</script>
</body>
</html>
""", user=u, theme=users[u]["theme"])

@app.route("/avatars/<f>")
def avatar(f): return send_from_directory(UPLOAD_FOLDER,f)

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# ===== SOCKET =====
@socketio.on("connect")
def connect():
    u=session["user"]
    tz=users[u]["timezone"]
    for m in history:
        m["time"]=format_time(m["raw"],tz)
        m["can_delete"]=(m["name"]==u)
    emit("history",history)

@socketio.on("message")
def msg(data):
    u=session["user"]
    text=highlight_mentions(data["msg"])

    if text.startswith("/ipban") and u in moderators:
        t=text.split("@")[1]
        ip_bans[t]=request.remote_addr
        save()
        return

    if text.startswith("/ipunban") and u in moderators:
        t=text.split("@")[1]
        ip_bans.pop(t,None)
        save()
        return

    now=datetime.utcnow()
    m={
        "id":str(uuid.uuid4()),
        "name":u,
        "username":users[u]["username"],
        "msg":text,
        "avatar":users[u]["avatar"],
        "raw":now.isoformat()
    }

    history.append(m)
    save()

    tz=users[u]["timezone"]
    m["time"]=format_time(m["raw"],tz)
    m["can_delete"]=True

    emit("message",m,broadcast=True)

@socketio.on("delete")
def delete(d):
    u=session["user"]
    for m in history:
        if m["id"]==d["id"] and m["name"]==u:
            m["msg"]="(deleted)"
            save()
            emit("delete",{"id":d["id"]},broadcast=True)
            break

# ===== RUN =====
public=ngrok.connect(5000)
print("Chat URL:",public)
import os
port = int(os.environ.get("PORT", 5000))
socketio.run(app, host="0.0.0.0", port=port)


