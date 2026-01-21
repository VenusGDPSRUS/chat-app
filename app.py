import eventlet
eventlet.monkey_patch()

from flask import Flask, request, redirect, session, render_template_string
from flask_socketio import SocketIO, emit
from werkzeug.security import generate_password_hash, check_password_hash
import os, json

app = Flask(__name__)
app.secret_key = "supersecretkey"

socketio = SocketIO(app, cors_allowed_origins="*")

USERS_FILE = "users.json"

if os.path.exists(USERS_FILE):
    users = json.load(open(USERS_FILE))
else:
    users = {}

def save():
    json.dump(users, open(USERS_FILE, "w"), indent=2)

@app.route("/", methods=["GET","POST"])
def login():
    if request.method == "POST":
        u = request.form["username"]
        p = request.form["password"]

        if u in users and check_password_hash(users[u]["password"], p):
            session["user"] = u
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

@app.route("/register", methods=["GET","POST"])
def register():
    if request.method == "POST":
        u = request.form["username"]
        p = request.form["password"]

        if u in users:
            return "User exists"

        users[u] = {"password": generate_password_hash(p)}
        save()
        session["user"] = u
        return redirect("/chat")

    return """
    <h2>Register</h2>
    <form method="POST">
      <input name="username"><br>
      <input type="password" name="password"><br>
      <button>Register</button>
    </form>
    """

@app.route("/chat")
def chat():
    if "user" not in session:
        return redirect("/")
    return render_template_string("""
    <h2>Chat</h2>
    <div id="chat"></div>
    <input id="msg">
    <button onclick="send()">Send</button>

    <script src="https://cdn.socket.io/4.5.4/socket.io.min.js"></script>
    <script>
    const socket = io();
    function send(){
      socket.emit("message", {msg: msg.value});
      msg.value="";
    }
    socket.on("message", d=>{
      chat.innerHTML += "<div>"+d+"</div>";
    });
    </script>
    """)

@socketio.on("message")
def handle(data):
    emit("message", data["msg"], broadcast=True)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host="0.0.0.0", port=port)


