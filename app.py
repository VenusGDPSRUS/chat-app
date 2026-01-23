import os
import re
import uuid
from datetime import datetime

from flask import (
    Flask, request, session,
    redirect, render_template_string, abort
)
from flask_socketio import SocketIO, emit
import psycopg2
from werkzeug.security import generate_password_hash, check_password_hash


# =======================
# CONFIG
# =======================

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set (Railway Variables)")

SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key")


# =======================
# APP INIT
# =======================

app = Flask(__name__)
app.config["SECRET_KEY"] = SECRET_KEY

socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode="threading"  # БЕЗ eventlet
)


# =======================
# DATABASE
# =======================

def get_db():
    return psycopg2.connect(DATABASE_URL, sslmode="require")


def init_db():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id UUID PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL
            );
            """)
            cur.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id UUID PRIMARY KEY,
                user_id UUID REFERENCES users(id),
                username TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL
            );
            """)
        conn.commit()


init_db()


# =======================
# HELPERS
# =======================

USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{3,20}$")


def current_user():
    return session.get("user")


def login_required():
    if "user" not in session:
        abort(401)


# =======================
# AUTH
# =======================

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]

        if not USERNAME_RE.match(username):
            return "Invalid username", 400

        pwd_hash = generate_password_hash(password)

        try:
            with get_db() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO users VALUES (%s,%s,%s,%s)",
                        (uuid.uuid4(), username, pwd_hash, datetime.utcnow())
                    )
                conn.commit()
        except Exception as e:
            return "Username already exists", 400

        return redirect("/login")

    return """
    <h2>Register</h2>
    <form method="post">
      <input name="username" placeholder="Username" required>
      <input name="password" type="password" placeholder="Password" required>
      <button>Register</button>
    </form>
    """


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, password_hash FROM users WHERE username=%s",
                    (username,)
                )
                row = cur.fetchone()

        if not row or not check_password_hash(row[1], password):
            return "Invalid credentials", 401

        session["user"] = {"id": str(row[0]), "username": username}
        return redirect("/")

    return """
    <h2>Login</h2>
    <form method="post">
      <input name="username" required>
      <input name="password" type="password" required>
      <button>Login</button>
    </form>
    """


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


# =======================
# CHAT PAGE
# =======================

@app.route("/")
def index():
    if "user" not in session:
        return redirect("/login")

    return render_template_string("""
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Chat</title>
<script src="https://cdn.socket.io/4.7.2/socket.io.min.js"></script>
<style>
body { font-family: system-ui; margin: 0; background:#111; color:#eee }
#chat { height: 90vh; overflow-y: auto; padding: 10px }
#input { position: fixed; bottom: 0; width: 100%; display:flex }
#input input { flex:1; padding:10px }
</style>
</head>
<body>

<div id="chat"></div>

<div id="input">
  <input id="msg" placeholder="Message">
  <button onclick="send()">Send</button>
</div>

<script>
const socket = io();

socket.on("message", data => {
  const div = document.createElement("div");
  div.textContent = "[" + data.time + "] " + data.user + ": " + data.text;
  document.getElementById("chat").appendChild(div);
});

function send() {
  const input = document.getElementById("msg");
  socket.emit("message", input.value);
  input.value = "";
}
</script>

</body>
</html>
    """)


# =======================
# SOCKET.IO
# =======================

@socketio.on("message")
def handle_message(text):
    if "user" not in session:
        return

    now = datetime.utcnow()

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO messages VALUES (%s,%s,%s,%s,%s)",
                (
                    uuid.uuid4(),
                    session["user"]["id"],
                    session["user"]["username"],
                    text,
                    now
                )
            )
        conn.commit()

# =======================
# RUN (RAILWAY SAFE)
# =======================

port = int(os.environ.get("PORT", 5000))

socketio.run(
    app,
    host="0.0.0.0",
    port=port,
    allow_unsafe_werkzeug=True
)

    emit(
        "message",
        {
            "user": session["user"]["username"],
            "text": text,
            "time": now.strftime("%H:%M:%S")
        },
        broadcast=True
    )


