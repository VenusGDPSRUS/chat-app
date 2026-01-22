import eventlet
eventlet.monkey_patch()

from flask import Flask, request, redirect, session, render_template_string, send_from_directory
from flask_socketio import SocketIO, emit
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import psycopg2, os, uuid, re

# ================= INIT =================
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "supersecret")
socketio = SocketIO(app, cors_allowed_origins="*")

UPLOAD_FOLDER = "avatars"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

DATABASE_URL = os.environ["DATABASE_URL"]

moderators = {"mahjong", "Admin123", "trollface69", "coaldev"}

USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{3,20}$")

# ================= DB =================
def db():
    return psycopg2.connect(DATABASE_URL, sslmode="require")

def init_db():
    with db() as conn:
        with conn.cursor() as c:
            c.execute("""
            CREATE TABLE IF NOT EXISTS users(
              nickname TEXT PRIMARY KEY,
              username TEXT UNIQUE,
              password TEXT,
              theme TEXT,
              timezone TEXT,
              avatar TEXT,
              created TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS messages(
              id UUID PRIMARY KEY,
              nickname TEXT,
              username TEXT,
              avatar TEXT,
              message TEXT,
              created TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS user_stats(
              nickname TEXT PRIMARY KEY,
              message_count INT DEFAULT 0,
              ban_count INT DEFAULT 0,
              first_message TIMESTAMP,
              last_message TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS ip_bans(
              ip TEXT PRIMARY KEY
            );
            """)
        conn.commit()

init_db()

# ================= HELPERS =================
def format_time(dt, tz):
    offsets = {"UTC":0,"UTC-8":-8,"UTC+3":3,"UTC+4":4}
    return (dt + timedelta(hours=offsets.get(tz,0))).strftime("%d/%m/%Y %H:%M:%S")

def highlight_mentions(text):
    return re.sub(r"@(\w+)", r"<span class='mention'>@\1</span>", text)

def get_tags(stats):
    tags=[]
    mc=stats["message_count"]
    bc=stats["ban_count"]

    if mc>=6000: tags.append(("Brother",""))
    elif mc>=5000: tags.append(("Friend",""))
    elif mc>=3500: tags.append(("Cousin",""))
    elif mc>=2000: tags.append(("Neighbor",""))
    elif mc>=500: tags.append(("Roulette",""))
    elif mc>=250: tags.append(("Worker",""))
    elif mc>=50: tags.append(("Stranger",""))

    if bc>=3: tags.append(("Dangerous",""))
    elif bc==2: tags.append(("Shell","#c7a15b"))
    elif bc==1: tags.append(("Crowded","#044569"))

    return tags

# ================= AUTH =================
@app.route("/", methods=["GET","POST"])
def login():
    if request.method=="POST":
        with db() as conn:
            with conn.cursor() as c:
                c.execute("SELECT password FROM users WHERE nickname=%s",(request.form["nickname"],))
                r=c.fetchone()
                if r and check_password_hash(r[0],request.form["password"]):
                    session["user"]=request.form["nickname"]
                    return redirect("/chat")
        return "Wrong login"

    return """
    <form method="POST">
      <input name="nickname" placeholder="Nickname"><br>
      <input type="password" name="password" placeholder="Password"><br>
      <button>Login</button>
    </form>
    <a href="/register">Register</a>
    """

@app.route("/register", methods=["GET","POST"])
def register():
    if request.method=="POST":
        nick=request.form["nickname"]
        uname=request.form["username"]

        if not USERNAME_RE.fullmatch(uname):
            return "Username must be латиницей (a-z, 0-9, _)"

        avatar=request.files["avatar"]
        fname=f"{uuid.uuid4()}.png"
        avatar.save(os.path.join(UPLOAD_FOLDER,fname))

        with db() as conn:
            with conn.cursor() as c:
                c.execute("""
                INSERT INTO users VALUES(%s,%s,%s,'dark','UTC',%s,%s)
                """,(nick,uname,generate_password_hash(request.form["password"]),fname,datetime.utcnow()))
                c.execute("INSERT INTO user_stats(nickname) VALUES(%s)",(nick,))
            conn.commit()

        session["user"]=nick
        return redirect("/chat")

    return """
    <form method="POST" enctype="multipart/form-data">
      <input name="nickname" placeholder="Nickname"><br>
      <input name="username" placeholder="@username (latin only)"><br>
      <input type="password" name="password" placeholder="Password"><br>
      <input type="file" name="avatar"><br>
      <button>Register</button>
    </form>
    """

# ================= CHAT =================
@app.route("/chat")
def chat():
    if "user" not in session:
        return redirect("/")
    return render_template_string(CHAT_HTML, me=session["user"])

@socketio.on("connect")
def load_history():
    me=session.get("user")
    if not me: return

    with db() as conn:
        with conn.cursor() as c:
            c.execute("SELECT timezone FROM users WHERE nickname=%s",(me,))
            tz=c.fetchone()[0]

            c.execute("""
            SELECT m.nickname,m.username,m.avatar,m.message,m.created,
                   s.message_count,s.ban_count
            FROM messages m
            JOIN user_stats s ON s.nickname=m.nickname
            ORDER BY m.created
            """)
            rows=c.fetchall()

    out=[]
    for r in rows:
        tags=get_tags({"message_count":r[5],"ban_count":r[6]})
        out.append({
            "name":r[0],
            "username":r[1],
            "avatar":r[2],
            "msg":r[3],
            "time":format_time(r[4],tz),
            "tags":tags,
            "can_delete":r[0]==me
        })

    emit("history",out)

@socketio.on("message")
def on_message(d):
    me=session["user"]
    now=datetime.utcnow()

    with db() as conn:
        with conn.cursor() as c:
            c.execute("""
            UPDATE user_stats
            SET message_count=message_count+1,
                last_message=%s,
                first_message=COALESCE(first_message,%s)
            WHERE nickname=%s
            """,(now,now,me))

            c.execute("SELECT username,avatar,timezone FROM users WHERE nickname=%s",(me,))
            u=c.fetchone()

            c.execute("""
            INSERT INTO messages VALUES(%s,%s,%s,%s,%s,%s)
            """,(str(uuid.uuid4()),me,u[0],u[1],highlight_mentions(d["msg"]),now))
        conn.commit()

    emit("message",{
        "name":me,
        "username":u[0],
        "avatar":u[1],
        "msg":highlight_mentions(d["msg"]),
        "time":format_time(now,u[2]),
        "can_delete":True,
        "tags":[]
    },broadcast=True)

# ================= IP BAN =================
@app.route("/ipban/<ip>")
def ipban(ip):
    if session.get("user") not in moderators:
        return "403"
    with db() as conn:
        with conn.cursor() as c:
            c.execute("INSERT INTO ip_bans VALUES(%s) ON CONFLICT DO NOTHING",(ip,))
        conn.commit()
    return "OK"

@app.route("/ipunban/<ip>")
def ipunban(ip):
    if session.get("user") not in moderators:
        return "403"
    with db() as conn:
        with conn.cursor() as c:
            c.execute("DELETE FROM ip_bans WHERE ip=%s",(ip,))
        conn.commit()
    return "OK"

# ================= HTML =================
CHAT_HTML="""
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
<script src="https://cdn.socket.io/4.5.4/socket.io.min.js"></script>
<style>
body{margin:0;font-family:'JetBrains Mono',monospace;background:#111;color:white}
.dark{background:#111;color:white}
.light{background:#eee;color:black}
.dracula{background:#282a36;color:#f8f8f2}
.crowdcontrol{background:#1c4975;color:#112336}
.aero{background:#80f6ff;color:#003b44}
.candy{background:#ff80b3;color:#4a001f}

.message{display:grid;grid-template-columns:80px 40px 1fr 24px;gap:10px;padding:6px}
.time{font-size:11px;opacity:.6}
.avatar{width:36px;height:36px;border-radius:50%}
.username{font-size:11px;opacity:.6}
.tag{font-size:11px;margin-right:4px}
.mention{color:#4da6ff;font-weight:600}
</style>
</head>
<body>
<h3>{{me}}</h3>
<div id="chat"></div>
<input id="msg" onkeydown="if(event.key==='Enter')send()">
<button onclick="send()">Send</button>

<script>
const s=io();
function render(m){
 let tags=m.tags.map(t=>`<span class="tag" style="color:${t[1]||''}">[${t[0]}]</span>`).join("");
 return `<div class="message">
 <div class="time">${m.time}</div>
 <img class="avatar" src="/avatars/${m.avatar}">
 <div><b>${m.name}</b> ${tags}<div class="username">@${m.username}</div>${m.msg}</div>
 </div>`;
}
s.on("history",d=>{chat.innerHTML="";d.forEach(m=>chat.innerHTML+=render(m))});
s.on("message",m=>chat.innerHTML+=render(m));
function send(){if(msg.value){s.emit("message",{msg:msg.value});msg.value=""}}
</script>
</body>
</html>
"""

@app.route("/avatars/<f>")
def avatar(f):
    return send_from_directory(UPLOAD_FOLDER,f)

if __name__=="__main__":
    socketio.run(app,host="0.0.0.0",port=int(os.environ.get("PORT",5000)))
