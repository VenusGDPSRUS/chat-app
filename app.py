import os
import psycopg
from flask import Flask, request, session, redirect, send_from_directory
from flask_socketio import SocketIO, emit, disconnect
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import uuid
import re

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev")
app.config['UPLOAD_FOLDER'] = 'static/avatars'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

# Создаем папку для аватарок при старте
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

socketio = SocketIO(app, async_mode="threading", manage_session=False)

DATABASE_URL = os.environ.get("DATABASE_URL")

# ---------- КОНФИГУРАЦИЯ ----------

# Часовые пояса от -12 до +14
TIMEZONES = {
    "-12:00": "Etc/GMT+12", "-11:00": "Pacific/Niue", "-10:00": "Pacific/Honolulu",
    "-09:00": "America/Anchorage", "-08:00": "America/Los_Angeles", "-07:00": "America/Denver",
    "-06:00": "America/Chicago", "-05:00": "America/New_York", "-04:00": "America/Caracas",
    "-03:00": "America/Sao_Paulo", "-02:00": "Atlantic/South_Georgia", "-01:00": "Atlantic/Azores",
    "+00:00": "UTC", "+01:00": "Europe/Berlin", "+02:00": "Europe/Kiev", "+03:00": "Europe/Moscow",
    "+04:00": "Asia/Dubai", "+05:00": "Asia/Tashkent", "+05:30": "Asia/Kolkata",
    "+06:00": "Asia/Almaty", "+07:00": "Asia/Bangkok", "+08:00": "Asia/Shanghai",
    "+09:00": "Asia/Tokyo", "+10:00": "Australia/Sydney", "+11:00": "Pacific/Noumea",
    "+12:00": "Pacific/Auckland", "+13:00": "Pacific/Tongatapu", "+14:00": "Pacific/Kiritimati"
}

# Список стран (код ISO для флага : название для отображения)
COUNTRIES = [
    ("af", "Afghanistan"), ("al", "Albania"), ("dz", "Algeria"), ("ad", "Andorra"),
    ("ao", "Angola"), ("ag", "Antigua and Barbuda"), ("ar", "Argentina"), ("am", "Armenia"),
    ("au", "Australia"), ("at", "Austria"), ("az", "Azerbaijan"), ("bs", "Bahamas"),
    ("bh", "Bahrain"), ("bd", "Bangladesh"), ("bb", "Barbados"), ("by", "Belarus"),
    ("be", "Belgium"), ("bz", "Belize"), ("bj", "Benin"), ("bt", "Bhutan"),
    ("bo", "Bolivia"), ("ba", "Bosnia and Herzegovina"), ("bw", "Botswana"), ("br", "Brazil"),
    ("bn", "Brunei"), ("bg", "Bulgaria"), ("bf", "Burkina Faso"), ("bi", "Burundi"),
    ("cv", "Cabo Verde"), ("kh", "Cambodia"), ("cm", "Cameroon"), ("ca", "Canada"),
    ("cf", "Central African Republic"), ("td", "Chad"), ("cl", "Chile"), ("cn", "China"),
    ("co", "Colombia"), ("km", "Comoros"), ("cg", "Congo (Brazzaville)"), ("cd", "Congo (Kinshasa)"),
    ("cr", "Costa Rica"), ("hr", "Croatia"), ("cu", "Cuba"), ("cy", "Cyprus"),
    ("cz", "Czechia"), ("dk", "Denmark"), ("dj", "Djibouti"), ("dm", "Dominica"),
    ("do", "Dominican Republic"), ("ec", "Ecuador"), ("eg", "Egypt"), ("sv", "El Salvador"),
    ("gq", "Equatorial Guinea"), ("er", "Eritrea"), ("ee", "Estonia"), ("sz", "Eswatini"),
    ("et", "Ethiopia"), ("fj", "Fiji"), ("fi", "Finland"), ("fr", "France"),
    ("ga", "Gabon"), ("gm", "Gambia"), ("ge", "Georgia"), ("de", "Germany"),
    ("gh", "Ghana"), ("gr", "Greece"), ("gd", "Grenada"), ("gt", "Guatemala"),
    ("gn", "Guinea"), ("gw", "Guinea-Bissau"), ("gy", "Guyana"), ("ht", "Haiti"),
    ("hn", "Honduras"), ("hu", "Hungary"), ("is", "Iceland"), ("in", "India"),
    ("id", "Indonesia"), ("ir", "Iran"), ("iq", "Iraq"), ("ie", "Ireland"),
    ("il", "Israel"), ("it", "Italy"), ("jm", "Jamaica"), ("jp", "Japan"),
    ("jo", "Jordan"), ("kz", "Kazakhstan"), ("ke", "Kenya"), ("ki", "Kiribati"),
    ("kw", "Kuwait"), ("kg", "Kyrgyzstan"), ("la", "Laos"), ("lv", "Latvia"),
    ("lb", "Lebanon"), ("ls", "Lesotho"), ("lr", "Liberia"), ("ly", "Libya"),
    ("li", "Liechtenstein"), ("lt", "Lithuania"), ("lu", "Luxembourg"), ("mg", "Madagascar"),
    ("mw", "Malawi"), ("my", "Malaysia"), ("mv", "Maldives"), ("ml", "Mali"),
    ("mt", "Malta"), ("mh", "Marshall Islands"), ("mr", "Mauritania"), ("mu", "Mauritius"),
    ("mx", "Mexico"), ("fm", "Micronesia"), ("md", "Moldova"), ("mc", "Monaco"),
    ("mn", "Mongolia"), ("me", "Montenegro"), ("ma", "Morocco"), ("mz", "Mozambique"),
    ("mm", "Myanmar"), ("na", "Namibia"), ("nr", "Nauru"), ("np", "Nepal"),
    ("nl", "Netherlands"), ("nz", "New Zealand"), ("ni", "Nicaragua"), ("ne", "Niger"),
    ("ng", "Nigeria"), ("kp", "North Korea"), ("mk", "North Macedonia"), ("no", "Norway"),
    ("om", "Oman"), ("pk", "Pakistan"), ("pw", "Palau"), ("ps", "Palestine"),
    ("pa", "Panama"), ("pg", "Papua New Guinea"), ("py", "Paraguay"), ("pe", "Peru"),
    ("ph", "Philippines"), ("pl", "Poland"), ("pt", "Portugal"), ("qa", "Qatar"),
    ("ro", "Romania"), ("ru", "Russia"), ("rw", "Rwanda"), ("kn", "Saint Kitts and Nevis"),
    ("lc", "Saint Lucia"), ("vc", "Saint Vincent and the Grenadines"), ("ws", "Samoa"),
    ("sm", "San Marino"), ("st", "Sao Tome and Principe"), ("sa", "Saudi Arabia"),
    ("sn", "Senegal"), ("rs", "Serbia"), ("sc", "Seychelles"), ("sl", "Sierra Leone"),
    ("sg", "Singapore"), ("sk", "Slovakia"), ("si", "Slovenia"), ("sb", "Solomon Islands"),
    ("so", "Somalia"), ("za", "South Africa"), ("kr", "South Korea"), ("ss", "South Sudan"),
    ("es", "Spain"), ("lk", "Sri Lanka"), ("sd", "Sudan"), ("sr", "Suriname"),
    ("se", "Sweden"), ("ch", "Switzerland"), ("sy", "Syria"), ("tj", "Tajikistan"),
    ("tz", "Tanzania"), ("th", "Thailand"), ("tl", "Timor-Leste"), ("tg", "Togo"),
    ("to", "Tonga"), ("tt", "Trinidad and Tobago"), ("tn", "Tunisia"), ("tr", "Turkey"),
    ("tm", "Turkmenistan"), ("tv", "Tuvalu"), ("ug", "Uganda"), ("ua", "Ukraine"),
    ("ae", "United Arab Emirates"), ("gb", "United Kingdom"), ("us", "United States"),
    ("uy", "Uruguay"), ("uz", "Uzbekistan"), ("vu", "Vanuatu"), ("va", "Vatican City"),
    ("ve", "Venezuela"), ("vn", "Vietnam"), ("ye", "Yemen"), ("zm", "Zambia"),
    ("zw", "Zimbabwe"), ("aq", "Antarctica")
]

# Штаты США
US_STATES = [
    ("", "No State"), ("al", "Alabama"), ("ak", "Alaska"), ("az", "Arizona"),
    ("ar", "Arkansas"), ("ca", "California"), ("co", "Colorado"), ("ct", "Connecticut"),
    ("de", "Delaware"), ("fl", "Florida"), ("ga", "Georgia"), ("hi", "Hawaii"),
    ("id", "Idaho"), ("il", "Illinois"), ("in", "Indiana"), ("ia", "Iowa"),
    ("ks", "Kansas"), ("ky", "Kentucky"), ("la", "Louisiana"), ("me", "Maine"),
    ("md", "Maryland"), ("ma", "Massachusetts"), ("mi", "Michigan"), ("mn", "Minnesota"),
    ("ms", "Mississippi"), ("mo", "Missouri"), ("mt", "Montana"), ("ne", "Nebraska"),
    ("nv", "Nevada"), ("nh", "New Hampshire"), ("nj", "New Jersey"), ("nm", "New Mexico"),
    ("ny", "New York"), ("nc", "North Carolina"), ("nd", "North Dakota"), ("oh", "Ohio"),
    ("ok", "Oklahoma"), ("or", "Oregon"), ("pa", "Pennsylvania"), ("ri", "Rhode Island"),
    ("sc", "South Carolina"), ("sd", "South Dakota"), ("tn", "Tennessee"), ("tx", "Texas"),
    ("ut", "Utah"), ("vt", "Vermont"), ("va", "Virginia"), ("wa", "Washington"),
    ("wv", "West Virginia"), ("wi", "Wisconsin"), ("wy", "Wyoming"), ("dc", "District of Columbia")
]

# ---------- DB ----------

def get_db():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set")
    # Простая логика重试 для подключения при старте БД
    import time
    for i in range(10):
        try:
            conn = psycopg.connect(DATABASE_URL)
            return conn
        except Exception as e:
            if i == 9: raise e
            time.sleep(2)

def init_db():
    db = get_db()
    c = db.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS users(
      id SERIAL PRIMARY KEY,
      username TEXT UNIQUE,
      password TEXT,
      nickname TEXT,
      avatar TEXT,
      country_code TEXT DEFAULT 'us',
      state_code TEXT DEFAULT '',
      theme TEXT DEFAULT 'matrix',
      tz_offset TEXT DEFAULT '+00:00',
      role TEXT DEFAULT 'user',
      banned_until TIMESTAMPTZ
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
      user_id INTEGER REFERENCES users(id),
      friend_id INTEGER REFERENCES users(id),
      PRIMARY KEY (user_id, friend_id)
    )
    """)
    db.commit()
    db.close()

if DATABASE_URL:
    try:
        init_db()
        print("Database initialized successfully.")
    except Exception as e:
        print(f"DB Init Error: {e}")

# ---------- AUTH & ROUTES ----------

@app.route("/", methods=["GET","POST"])
def login():
    if request.method=="POST":
        u = request.form["username"]
        p = request.form["password"]
        db=get_db(); c=db.cursor()
        c.execute("SELECT id FROM users WHERE username=%s AND password=%s",(u,p))
        r=c.fetchone()
        db.close()
        if r:
            session["user_id"]=r[0]
            return redirect("/chat")
        return "Invalid credentials", 401
    return "<form method=post><input name=username><input name=password type=password><button>Login</button></form><a href=/register>Register</a>"

@app.route("/register", methods=["GET","POST"])
def register():
    if request.method=="POST":
        db=get_db(); c=db.cursor()
        try:
            c.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM users")
            new_id = c.fetchone()[0]
            
            avatar = None
            if 'avatar_file' in request.files:
                file = request.files['avatar_file']
                if file and file.filename != '':
                    ext = file.filename.rsplit('.', 1)[1].lower()
                    new_filename = f"u{new_id}_{uuid.uuid4().hex[:8]}.{ext}"
                    filepath = os.path.join(app.config['UPLOAD_FOLDER'], new_filename)
                    file.save(filepath)
                    avatar = new_filename
            
            c.execute(
              "INSERT INTO users(id, username, password, avatar, nickname, country_code, state_code) VALUES(%s,%s,%s,%s,%s,%s,%s)",
              (
                new_id,
                request.form["username"],
                request.form["password"],
                avatar,
                request.form["username"],
                request.form.get("country", "us"),
                request.form.get("state", "")
              )
            )
            db.commit()
            db.close()
            return redirect("/")
        except psycopg.IntegrityError:
             db.close()
             return "Username exists!", 400
    
    country_opts = "".join([f'<option value="{code}"{" selected" if code=="us" else ""}>{name}</option>' for code, name in COUNTRIES])
    state_opts = "".join([f'<option value="{code}">{name}</option>' for code, name in US_STATES])
    tz_opts = "".join([f'<option value="{tz}">{tz}</option>' for tz in TIMEZONES.keys()])
    
    return f"""
    <body style="background:#000;color:#0f0;font-family:Courier New">
    <h3>Register</h3>
    <form method=post enctype="multipart/form-data">
      <input name=username placeholder="Username"><br>
      <input name=password type=password placeholder="Password"><br>
      <label>Avatar: <input type=file name=avatar_file accept="image/*"></label><br>
      Country: <select name=country id="country" onchange="toggleState()">{country_opts}</select><br>
      State (US only): <select name=state id="state" style="display:none">{state_opts}</select><br>
      Timezone: <select name=tz>{tz_opts}</select><br>
      <button>Register</button>
    </form>
    <script>
      function toggleState() {{
        const c = document.getElementById('country').value;
        const s = document.getElementById('state');
        s.style.display = (c === 'us') ? 'inline-block' : 'none';
      }}
    </script>
    """

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# ---------- SOCKET & CHAT ----------

connected_users = {}

@socketio.on('connect')
def handle_connect():
    uid = session.get('user_id')
    if uid:
        connected_users[request.sid] = uid

@socketio.on('disconnect')
def handle_disconnect():
    connected_users.pop(request.sid, None)

@socketio.on('msg')
def handle_msg(text):
    uid = connected_users.get(request.sid)
    if not uid: return
    
    db = get_db()
    c = db.cursor()
    
    # Проверка бана
    c.execute("SELECT banned_until FROM users WHERE id=%s", (uid,))
    row = c.fetchone()
    if row and row[0]:
        if row[0] > datetime.now(row[0].tzinfo):
            db.close()
            emit('error', 'You are banned!')
            return
        else:
            # Разбан по времени
            c.execute("UPDATE users SET banned_until=NULL WHERE id=%s", (uid,))
            db.commit()

    # Обработка команд модератора
    if text.startswith('/'):
        process_command(text, uid, c, db)
        db.close()
        return

    # Отправка сообщения
    c.execute("SELECT nickname, avatar, country_code, state_code, tz_offset FROM users WHERE id=%s", (uid,))
    data = c.fetchone()
    if not data:
        db.close()
        return
    
    nick, av, country, state, tz_off = data
    c.execute("INSERT INTO messages(user_id, content) VALUES(%s,%s)", (uid, text))
    db.commit()
    
    now = datetime.now(ZoneInfo(TIMEZONES.get(tz_off, 'UTC'))).strftime("%H:%M:%S")
    
    emit("msg", {
        "nick": nick,
        "avatar": av,
        "country": country,
        "state": state,
        "text": text,
        "time": now,
        "user_id": uid
    }, broadcast=True)
    db.close()

def process_command(text, uid, c, db):
    parts = text.split()
    cmd = parts[0].lower()
    
    # Проверка прав
    c.execute("SELECT username, role FROM users WHERE id=%s", (uid,))
    me = c.fetchone()
    if not me: return
    my_name, my_role = me
    is_admin = (my_name == "Dfghj")
    is_mod = (is_admin or my_role == 'moderator')

    if cmd == '/clear' and is_mod:
        c.execute("DELETE FROM messages")
        db.commit()
        emit('sys', 'Chat cleared by moderator', broadcast=True)
        
    elif cmd == '/ban' and is_mod:
        if len(parts) < 2: return
        target_id = int(parts[1].replace('@', ''))
        c.execute("UPDATE users SET banned_until='2099-01-01' WHERE id=%s", (target_id,))
        db.commit()
        emit('sys', f'User {target_id} banned permanently', broadcast=True)
        
    elif cmd == '/mute' and is_mod:
        if len(parts) < 3: return
        target_id = int(parts[1].replace('@', ''))
        hours = int(parts[2])
        until = datetime.now() + timedelta(hours=hours)
        c.execute("UPDATE users SET banned_until=%s WHERE id=%s", (until, target_id))
        db.commit()
        emit('sys', f'User {target_id} muted for {hours} hours', broadcast=True)
        
    elif cmd == '/del' and is_admin:
        if len(parts) < 2: return
        target_id = int(parts[1].replace('@', ''))
        c.execute("DELETE FROM users WHERE id=%s", (target_id,))
        c.execute("DELETE FROM messages WHERE user_id=%s", (target_id,))
        db.commit()
        emit('sys', f'User {target_id} deleted by Admin', broadcast=True)

@app.route("/chat")
def chat():
    if "user_id" not in session: return redirect("/")
    db=get_db(); c=db.cursor()
    
    c.execute("SELECT nickname,avatar,country_code,state_code,theme,tz_offset FROM users WHERE id=%s",(session["user_id"],))
    nick,av,country,state,theme,tz_off = c.fetchone()
    
    c.execute("SELECT friend_id FROM friendships WHERE user_id=%s", (session["user_id"],))
    friend_ids = [r[0] for r in c.fetchall()]
    
    c.execute("""
        SELECT m.content, m.created_at, u.nickname, u.avatar, u.country_code, u.state_code, u.tz_offset, u.id
        FROM messages m JOIN users u ON m.user_id = u.id
        ORDER BY m.created_at ASC LIMIT 100
    """)
    
    msgs = []
    for row in c.fetchall():
        content, created_at, m_nick, m_av, m_c, m_s, m_tz, m_id = row
        local_time = created_at.astimezone(ZoneInfo(TIMEZONES.get(m_tz, 'UTC'))).strftime("%H:%M:%S")
        msgs.append({
            "text": content, "time": local_time, "nick": m_nick,
            "avatar": m_av, "country": m_c, "state": m_s, "user_id": m_id
        })
    
    db.close()
    
    html = ""
    for m in msgs:
        is_fr = m["user_id"] in friend_ids
        style = 'border: 2px solid #0f0; background: rgba(0,255,0,0.1); padding:5px;' if is_fr else ''
        
        # Флаги
        flags_html = f'<img src="https://flagcdn.com/24x18/{m["country"]}.png" alt="{m["country"]}">'
        if m["country"] == 'us' and m["state"]:
            flags_html += f'<img src="https://flagcdn.com/24x18/us-{m["state"]}.png" alt="{m["state"]}" style="margin-left:2px;">'
            
        html += f'''
        <div style="{style}">
          {f'<img src="/static/avatars/{m["avatar"]}" width=32>' if m["avatar"] else ''}
          <b>{m["nick"]}</b> {flags_html} <small>({m["time"]})</small><br>
          {m["text"]}
        </div>'''

    return f"""
<!doctype html>
<body style="margin:0;background:#000;color:#0f0;font-family:Courier New">
<div style="padding:10px;border-bottom:1px solid #0f0">
  {nick} | <a href=/settings>Settings</a> | <a href=/logout>Logout</a>
</div>
<div id=chat style="height:70vh;overflow:auto;padding:10px">{html}</div>
<div style="display:flex">
  <input id=msg style="flex:1">
  <button onclick=send()>Send</button>
</div>
<script src="https://cdn.socket.io/4.7.2/socket.io.min.js"></script>
<script>
let s=io();
const friends = {friend_ids};

s.on("msg", m => {{
    const isFr = friends.includes(m.user_id);
    const style = isFr ? 'border: 2px solid #0f0; background: rgba(0,255,0,0.1); padding:5px;' : '';
    
    let flags = `<img src="https://flagcdn.com/24x18/${{m.country}}.png">`;
    if(m.country === 'us' && m.state) {{
        flags += `<img src="https://flagcdn.com/24x18/us-${{m.state}}.png" style="margin-left:2px;">`;
    }}
    
    const avHtml = m.avatar ? `<img src="/static/avatars/${{m.avatar}}" width=32>` : '';
    
    chat.innerHTML += `<div style="${{style}}">${{avHtml}}<b>${{m.nick}}</b> ${{flags}} <small>(${{m.time}})</small><br>${{m.text}}</div>`;
    chat.scrollTop = chat.scrollHeight;
}});

s.on("sys", msg => {{
    chat.innerHTML += `<div style="color:red; font-weight:bold;">[SYSTEM]: ${{msg}}</div>`;
    chat.scrollTop = chat.scrollHeight;
}});

function send(){{
    const t = msg.value.trim();
    if(t){{ s.emit("msg", t); msg.value=""; }}
}}
</script>
</body>
"""

@app.route("/settings", methods=["GET","POST"])
def settings():
    if "user_id" not in session: return redirect("/")
    db=get_db(); c=db.cursor()
    
    if request.method=="POST":
        av = request.form.get("avatar", "")
        if 'avatar_file' in request.files:
            file = request.files['avatar_file']
            if file and file.filename != '':
                ext = file.filename.rsplit('.', 1)[1].lower()
                fn = f"u{session['user_id']}_{uuid.uuid4().hex[:8]}.{ext}"
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], fn))
                av = fn
        
        c.execute("""UPDATE users SET nickname=%s, avatar=%s, country_code=%s, state_code=%s, theme=%s, tz_offset=%s WHERE id=%s""",
                  (request.form["nickname"], av, request.form["country"], request.form["state"], request.form["theme"], request.form["tz"], session["user_id"]))
        db.commit()
        db.close()
        return redirect("/chat")
    
    c.execute("SELECT nickname,avatar,country_code,state_code,theme,tz_offset FROM users WHERE id=%s",(session["user_id"],))
    u = c.fetchone()
    db.close()
    
    c_opts = "".join([f'<option value="{c}"{" selected" if c==u[2] else ""}>{n}</option>' for c,n in COUNTRIES])
    s_opts = "".join([f'<option value="{s}"{" selected" if s==u[3] else ""}>{n}</option>' for s,n in US_STATES])
    t_opts = "".join([f'<option value="{t}"{" selected" if t==u[5] else ""}>{t}</option>' for t in TIMEZONES.keys()])
    
    return f"""
    <body style="background:#000;color:#0f0;font-family:Courier New">
    <h3>Settings</h3>
    <form method=post enctype="multipart/form-data">
      Nick: <input name=nickname value="{u[0]}"><br>
      Avatar: <input type=file name=avatar_file><br>
      Country: <select name=country id="country" onchange="toggleState()">{c_opts}</select><br>
      State: <select name=state id="state" style="display:{'inline-block' if u[2]=='us' else 'none'}">{s_opts}</select><br>
      Theme: <select name=theme>
        {''.join([f'<option value="{t}"{" selected" if t==u[4] else ""}>{t}</option>' for t in ['matrix','dark','light']])}
      </select><br>
      TZ: <select name=tz>{t_opts}</select><br>
      <button>Save</button>
    </form>
    <script>
      function toggleState() {{
        const c = document.getElementById('country').value;
        const s = document.getElementById('state');
        s.style.display = (c === 'us') ? 'inline-block' : 'none';
      }}
    </script>
    """

if __name__=="__main__":
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host="0.0.0.0", port=port, debug=False, allow_unsafe_werkzeug=True)
