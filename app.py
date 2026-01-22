import eventlet
eventlet.monkey_patch()

from flask import Flask, request, redirect, session, send_from_directory, render_template_string
from flask_socketio import SocketIO, emit
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import os, json, uuid, re

# ================= INIT =================
app = Flask(__name__)
app.secret_key = "supersecretkey"
socketio = SocketIO(app, cors_allowed_origins="*")

UPLOAD_FOLDER = "avatars"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

USERS_FILE = "users.json"
HISTORY_FILE = "chat_history.json"
USER_STATS_FILE = "user_stats.json"

moderators = {"mahjong", "Admin123", "trollface69", "coaldev"}

# ================= LOAD WITH RESET =================
def load_users():
    if not os.path.exists(USERS_FILE):
        return {}

    data = json.load(open(USERS_FILE, "r", encoding="utf-8"))
    fixed = {}

    for nick, u in data.items():
        if not all(k in u for k in ("password", "username", "theme", "timezone", "avatar")):
            continue
        fixed[nick] = u

    return fixed

def load_history():
    if os.path.exists(HISTORY_FILE):
        return json.load(open(HISTORY_FILE, "r", encoding="utf-8"))
    return []

def load_user_stats():
    if os.path.exists(USER_STATS_FILE):
        return json.load(open(USER_STATS_FILE, "r", encoding="utf-8"))
    return {}

users = load_users()
history = load_history()
user_stats = load_user_stats()

def save():
    json.dump(users, open(USERS_FILE,"w",encoding="utf-8"), ensure_ascii=False, indent=2)
    json.dump(history, open(HISTORY_FILE,"w",encoding="utf-8"), ensure_ascii=False, indent=2)
    json.dump(user_stats, open(USER_STATS_FILE,"w",encoding="utf-8"), ensure_ascii=False, indent=2)

# ================= USER STATS FUNCTIONS =================
def update_user_stats(nickname):
    """Initialize or update user statistics"""
    if nickname not in user_stats:
        user_stats[nickname] = {
            "message_count": 0,
            "ban_count": 0,
            "first_message_time": None,
            "last_message_time": None
        }
    return user_stats[nickname]

def get_user_tags(nickname):
    """Calculate tags for a user based on their stats"""
    if nickname not in user_stats:
        return []
    
    stats = user_stats[nickname]
    tags = []
    
    # Message count tags
    msg_count = stats["message_count"]
    if msg_count >= 6000:
        tags.append(("[Brother]", ""))
    elif msg_count >= 5000:
        tags.append(("[Friend]", ""))
    elif msg_count >= 3500:
        tags.append(("[Cousin]", ""))
    elif msg_count >= 2000:
        tags.append(("[Neighbor]", ""))
    elif msg_count >= 500:
        tags.append(("[Roulette]", ""))
    elif msg_count >= 250:
        tags.append(("[Worker]", ""))
    elif msg_count >= 50:
        tags.append(("[Stranger]", ""))
    
    # Ban count tags
    ban_count = stats["ban_count"]
    if ban_count >= 3:
        tags.append(("[Dangerous]", ""))
    elif ban_count >= 2:
        tags.append(("[Shell]", "#c7a15b"))  # Special color for Shell tag
    elif ban_count >= 1:
        tags.append(("[Crowded]", ""))
    
    # Time-based tags
    if stats["first_message_time"]:
        first_msg_time = datetime.fromisoformat(stats["first_message_time"])
        time_since_first = datetime.utcnow() - first_msg_time
        days = time_since_first.days
        hours = time_since_first.seconds // 3600
        
        if days >= 365:
            tags.append(("[Hydrogen]", ""))
        elif days >= 100:
            tags.append(("[Petrol]", ""))
        elif days >= 30:
            tags.append(("[Diesel]", ""))
        elif days >= 14:
            tags.append(("[Steam]", ""))
        elif days >= 5:
            tags.append(("[Oil]", ""))
        elif days >= 2 or (days == 1 and hours >= 12):
            tags.append(("[Coal]", ""))
        elif hours >= 12:
            tags.append(("[Biomass]", ""))
    
    return tags

def increment_message_count(nickname):
    """Increment message count and update timestamps"""
    stats = update_user_stats(nickname)
    stats["message_count"] += 1
    stats["last_message_time"] = datetime.utcnow().isoformat()
    if not stats["first_message_time"]:
        stats["first_message_time"] = stats["last_message_time"]
    save()

def increment_ban_count(nickname):
    """Increment ban count for a user"""
    stats = update_user_stats(nickname)
    stats["ban_count"] += 1
    save()

# ================= HELPERS =================
def format_time(iso, tz):
    base = datetime.fromisoformat(iso)
    offsets = {"UTC":0,"UTC-8":-8,"UTC+3":3,"UTC+4":4}
    base += timedelta(hours=offsets.get(tz,0))
    return base.strftime("%d/%m/%Y %H:%M:%S")

def highlight_mentions(text):
    for u in users.values():
        text = re.sub(
            rf"@{u['username']}\b",
            f"<span class='mention'>@{u['username']}</span>",
            text
        )
    return text

def format_tags_html(tags):
    """Format tags as HTML spans with inline styles"""
    if not tags:
        return ""
    
    html_tags = []
    for tag, color in tags:
        if color:
            html_tags.append(f'<span class="user-tag" style="color:{color}">{tag}</span>')
        else:
            html_tags.append(f'<span class="user-tag">{tag}</span>')
    
    return " ".join(html_tags)

# ================= AUTH =================
@app.route("/", methods=["GET","POST"])
def login():
    if request.method == "POST":
        nick = request.form["nickname"]
        pwd = request.form["password"]
        if nick in users and check_password_hash(users[nick]["password"], pwd):
            session["user"] = nick
            return redirect("/chat")
        return "Wrong login"
    return """
    <h2>Login</h2>
<form method="POST">
  <input name="nickname" placeholder="Nickname"><br>
  <input type="password" name="password" placeholder="Password"><br>
  <button>Login</button>
</form>
    <a href="/register">Register</a>
    """

@app.route("/register", methods=["GET","POST"])
def register():
    if request.method == "POST":
        nick = request.form["nickname"]
        uname = request.form["username"]
        pwd = request.form["password"]

        if " " in uname:
            return "Username cannot contain spaces"
        if nick in users:
            return "Nickname already exists"
        if any(u["username"] == uname for u in users.values()):
            return "Username taken"

        avatar = request.files["avatar"]
        fname = f"{nick}.png"
        avatar.save(os.path.join(UPLOAD_FOLDER, fname))

        users[nick] = {
            "password": generate_password_hash(pwd),
            "username": uname,
            "avatar": fname,
            "theme": "dark",
            "timezone": "UTC",
            "last_nick": None
        }
        
        # Initialize user stats
        update_user_stats(nick)
        save()
        
        session["user"] = nick
        return redirect("/chat")

    return """
    <h2>Register</h2>
    <form method="POST" enctype="multipart/form-data">
      <input name="nickname" placeholder="Nickname"><br>
      <input name="username" placeholder="@username"><br>
      <input type="password" name="password"><br>
      <input type="file" name="avatar"><br>
      <button>Register</button>
    </form>
    """

# ================= SETTINGS =================
@app.route("/settings", methods=["GET","POST"])
def settings():
    if "user" not in session:
        return redirect("/")
    me = session["user"]
    u = users[me]

    if request.method == "POST":
        if "theme" in request.form:
            u["theme"] = request.form["theme"]
        if "tz" in request.form:
            u["timezone"] = request.form["tz"]
        if "avatar" in request.files:
            request.files["avatar"].save(os.path.join(UPLOAD_FOLDER, u["avatar"]))
        save()

    return """
    <h2>Settings</h2>
    <form method="POST">
      <select name="theme">
        <option>dark</option><option>light</option><option>matrix</option>
        <option>ocean</option><option>sunset</option><option>neon</option>
        <option>dracula</option><option>crowdcontrol</option>
        <option>aero</option><option>candy</option>
      </select>
      <button>Theme</button>
    </form><br>

    <form method="POST">
      <select name="tz">
        <option>UTC</option><option>UTC-8</option>
        <option>UTC+3</option><option>UTC+4</option>
      </select>
      <button>Timezone</button>
    </form><br>

    <form method="POST" enctype="multipart/form-data">
      <input type="file" name="avatar">
      <button>Change Avatar</button>
    </form>

    <br><a href="/chat">Back</a>
    """

# ================= ADMIN BAN ENDPOINT =================
@app.route("/admin/ban/<nickname>", methods=["POST"])
def ban_user(nickname):
    """Endpoint for moderators to ban users (increment ban count)"""
    if "user" not in session or session["user"] not in moderators:
        return "Unauthorized", 403
    
    if nickname in users:
        increment_ban_count(nickname)
        return f"User {nickname} ban count incremented"
    return "User not found", 404

# ================= CHAT =================
@app.route("/chat")
def chat():
    if "user" not in session:
        return redirect("/")
    me = session["user"]
    return render_template_string(CHAT_HTML, me=me, theme=users[me]["theme"])

@app.route("/avatars/<f>")
def avatar(f):
    return send_from_directory(UPLOAD_FOLDER, f)

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# ================= SOCKET =================
@socketio.on("connect")
def on_connect():
    if "user" not in session:
        return
    me = session["user"]
    tz = users[me]["timezone"]

    out = []
    for m in history:
        m2 = m.copy()
        m2["time"] = format_time(m["raw"], tz)
        m2["can_delete"] = (m["name"] == me)
        m2["is_admin"] = (m["name"] in moderators)
        
        # Add tags to message
        tags = get_user_tags(m["name"])
        m2["tags_html"] = format_tags_html(tags)
        
        out.append(m2)

    emit("history", out)

@socketio.on("message")
def on_msg(data):
    me = session["user"]
    now = datetime.utcnow()

    # Increment message count for user
    increment_message_count(me)
    
    m = {
        "id": str(uuid.uuid4()),
        "name": me,
        "username": users[me]["username"],
        "avatar": users[me]["avatar"],
        "raw": now.isoformat(),
        "msg": highlight_mentions(data["msg"])
    }

    history.append(m)
    save()

    m["time"] = format_time(m["raw"], users[me]["timezone"])
    m["can_delete"] = True
    m["is_admin"] = (me in moderators)
    
    # Add tags to message
    tags = get_user_tags(me)
    m["tags_html"] = format_tags_html(tags)

    emit("message", m, broadcast=True)

@socketio.on("delete")
def on_delete(d):
    me = session["user"]
    for m in history:
        if m["id"] == d["id"] and m["name"] == me:
            m["msg"] = "(deleted)"
            save()
            emit("delete", {"id": d["id"]}, broadcast=True)
            break

# ================= HTML =================
CHAT_HTML = """<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<script src="https://cdn.socket.io/4.5.4/socket.io.min.js"></script>
<style>
body{margin:0;font-family:Courier New}
.dark{background:#111;color:white}
.light{background:#eee;color:black}
.matrix{background:black;color:#0f0}
.ocean{background:#002;color:#0ff}
.sunset{background:#300;color:#ff9}
.neon{background:#000;color:#f0f}
.dracula{background:#282a36;color:#f8f8f2}
.crowdcontrol{background:#0ff;color:#002}
.aero{background:#80f6ff;color:#003b44}
.candy{background:#ff80b3;color:#4a001f}

#chat{padding:10px;display:flex;flex-direction:column;gap:8px}
.message{display:grid;grid-template-columns:110px 42px 1fr 24px;gap:10px}
.time{font-size:11px;opacity:.6}
.avatar{width:36px;height:36px;border-radius:50%}
.header{display:flex;gap:6px;align-items:baseline;flex-wrap:wrap}
.username{font-size:11px;opacity:.6}
.user-tag{font-size:11px;opacity:0.8;margin-right:4px;}
.delete{background:none;border:none;cursor:pointer;opacity:.5}
.delete:hover{opacity:1}
.mention{color:#4da6ff;font-weight:bold}

@media(max-width:600px){
 .message{grid-template-columns:42px 1fr 24px}
 .time{display:none}
}
</style>
</head>
<body class="{{theme}}">
<h3>{{me}}</h3>
<a href="/settings">Settings</a> | <a href="/logout">Logout</a>
<div id="chat"></div>
<input id="msg" onkeydown="if(event.key==='Enter')send()">
<button onclick="send()">Send</button>

<script>
const socket=io();
function html(m){
 return `<div class="message" id="m${m.id}">
  <div class="time">${m.time.replace(" ","<br>")}</div>
  <img class="avatar" src="/avatars/${m.avatar}">
  <div>
   <div class="header">
    <b>${m.name}</b>
    ${m.tags_html}
    <span class="username">@${m.username}</span>
   </div>
   <div>${m.msg}</div>
  </div>
  ${m.can_delete?`<button class="delete" onclick="del('${m.id}')">✕</button>`:""}
 </div>`;
}
socket.on("history",d=>{chat.innerHTML="";d.forEach(m=>chat.innerHTML+=html(m));});
socket.on("message",m=>chat.innerHTML+=html(m));
socket.on("delete",d=>document.getElementById("m"+d.id).innerHTML="(deleted)");
function send(){if(msg.value.trim())socket.emit("message",{msg:msg.value});msg.value="";}
function del(id){socket.emit("delete",{id});}
</script>
</body></html>
"""

# ================= RUN =================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host="0.0.0.0", port=port)

