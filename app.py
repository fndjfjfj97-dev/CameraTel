
import secrets
import string
from functools import wraps

from flask import Flask, request, session, redirect, url_for, render_template_string
from flask_socketio import SocketIO, emit
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config["SECRET_KEY"] = secrets.token_hex(32)

socketio = SocketIO(
    app,
    async_mode="threading",
    cors_allowed_origins="*"
)

users = {}
rooms = {}
sid_to_code = {}


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if "username" not in session:
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper


STYLE = """
<style>
* {box-sizing:border-box}
body {
    margin:0;
    background:#080b12;
    color:white;
    font-family:Arial,sans-serif;
    min-height:100vh;
    display:flex;
    justify-content:center;
    align-items:center;
    padding:20px;
}
.panel {
    width:min(560px,100%);
    background:#111827;
    border:1px solid #263247;
    border-radius:22px;
    padding:25px;
}
h1 {margin-top:0}
.sub,.muted {color:#9aa8bc}
input {
    width:100%;
    padding:14px;
    margin:8px 0 15px;
    border-radius:10px;
    border:1px solid #35445c;
    background:#0b1220;
    color:white;
    font-size:16px;
}
button,.btn {
    display:inline-block;
    padding:13px 17px;
    border:0;
    border-radius:10px;
    background:#2563eb;
    color:white;
    font-weight:bold;
    cursor:pointer;
    text-decoration:none;
}
button:disabled {opacity:.45}
.secondary {background:#263449}
.danger {background:#dc2626}
.green {color:#4ade80}
.row {display:flex;gap:10px;flex-wrap:wrap;margin-top:14px}
video {
    width:100%;
    background:#02040a;
    border-radius:15px;
    max-height:65vh;
}
.code {
    font-size:29px;
    font-weight:bold;
    letter-spacing:3px;
    color:#67e8a5;
    background:#07150f;
    padding:15px;
    text-align:center;
    border-radius:12px;
}
.note {
    background:#1d293b;
    padding:13px;
    border-radius:12px;
    line-height:1.5;
}
a {color:#93c5fd}
.status {margin:15px 0;color:#aab8ca}
</style>
"""

LOGIN = """<!doctype html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>CameraTel — Вход</title>
""" + STYLE + """</head>
<body><main class="panel">
<h1>CameraTel</h1>
<p class="sub">Аккаунт зрителя</p>
{% if error %}<p style="color:#fca5a5">{{error}}</p>{% endif %}
<form method="post">
<label>Логин</label>
<input name="username" required>
<label>Пароль</label>
<input name="password" type="password" required>
<button type="submit">Войти</button>
</form>
<p>Нет аккаунта? <a href="/register">Зарегистрироваться</a></p>
</main></body></html>"""


REGISTER = """<!doctype html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>CameraTel — Регистрация</title>
""" + STYLE + """</head>
<body><main class="panel">
<h1>CameraTel</h1>
<p class="sub">Создание аккаунта</p>
{% if error %}<p style="color:#fca5a5">{{error}}</p>{% endif %}
<form method="post">
<label>Логин</label>
<input name="username" required minlength="3" maxlength="32">
<label>Пароль</label>
<input name="password" type="password" required minlength="8">
<button type="submit">Создать аккаунт</button>
</form>
<p>Уже есть аккаунт? <a href="/login">Войти</a></p>
</main></body></html>"""


HOME = """<!doctype html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>CameraTel</title>
""" + STYLE + """</head>
<body><main class="panel">
<h1>CameraTel</h1>
<p class="sub">Подключение камеры телефона</p>
<div class="note">
Откройте Camera на телефоне, включите камеру
и поделитесь кодом со зрителем.
</div>
<div class="row">
<a class="btn" href="/camera">Открыть Camera</a>
<a class="btn secondary" href="/viewer">Открыть Viewer</a>
</div>
</main></body></html>"""


CAMERA = """<!doctype html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>CameraTel — Camera</title>
""" + STYLE + """
<script src="https://cdn.socket.io/4.7.5/socket.io.min.js"></script>
</head><body><main class="panel">

<h1>CameraTel / Camera</h1>
<p class="sub">Камера телефона</p>

<video id="localVideo" autoplay playsinline muted></video>

<div class="status" id="status">
Нажмите «Включить камеру».
</div>

<div id="codeBox" style="display:none">
<p>Код для зрителя:</p>
<div class="code" id="pairCode"></div>
</div>

<div class="row">
<button id="startBtn">Включить камеру</button>
<button id="stopBtn" class="danger" disabled>Остановить</button>
</div>

<p><a href="/">На главную</a></p>

</main>

<script>
const socket = io();

const video = document.getElementById('localVideo');
const statusEl = document.getElementById('status');
const startBtn = document.getElementById('startBtn');
const stopBtn = document.getElementById('stopBtn');

let stream = null;
let pc = null;
let pendingIce = [];

const rtcConfig = {
    iceServers: [
        {urls:'stun:stun.l.google.com:19302'}
    ]
};

function status(text, live=false) {
    statusEl.textContent = text;
    statusEl.className = live ? 'status green' : 'status';
}

function makePeer() {
    pc = new RTCPeerConnection(rtcConfig);

    stream.getTracks().forEach(track => {
        pc.addTrack(track, stream);
    });

    pc.onicecandidate = e => {
        if (e.candidate) {
            socket.emit('signal', {
                type:'ice',
                candidate:e.candidate
            });
        }
    };

    pc.onconnectionstatechange = () => {
        if (pc) {
            status(
                'Соединение: ' + pc.connectionState,
                pc.connectionState === 'connected'
            );
        }
    };
}

async function flushIce() {
    for (const candidate of pendingIce) {
        try {
            await pc.addIceCandidate(candidate);
        } catch(e) {
            console.error(e);
        }
    }
    pendingIce = [];
}

socket.on('camera_created', data => {
    document.getElementById('pairCode').textContent = data.code;
    document.getElementById('codeBox').style.display = 'block';
    status('Камера включена. Ожидаем зрителя...', true);
});

socket.on('viewer_joined', async () => {
    if (!stream) return;

    try {
        if (pc) pc.close();

        pendingIce = [];
        makePeer();

        const offer = await pc.createOffer();
        await pc.setLocalDescription(offer);

        socket.emit('signal', {
            type:'offer',
            description:pc.localDescription
        });

        status('Зритель подключается...', true);

    } catch(e) {
        status('Ошибка: ' + e.message);
    }
});

socket.on('signal', async data => {
    if (!pc) return;

    try {
        if (data.type === 'answer') {
            await pc.setRemoteDescription(data.description);
            await flushIce();
            status('LIVE — видео передаётся', true);

        } else if (data.type === 'ice' && data.candidate) {
            if (pc.remoteDescription) {
                await pc.addIceCandidate(data.candidate);
            } else {
                pendingIce.push(data.candidate);
            }
        }
    } catch(e) {
        console.error(e);
    }
});

socket.on('viewer_left', () => {
    if (pc) {
        pc.close();
        pc = null;
    }
    pendingIce = [];
    status('Зритель отключился.', true);
});

socket.on('connect_error', e => {
    status('Ошибка сервера: ' + e.message);
});

startBtn.onclick = async () => {
    startBtn.disabled = true;

    try {
        stream = await navigator.mediaDevices.getUserMedia({
            audio:false,
            video:{
                facingMode:{ideal:'environment'},
                width:{ideal:1280},
                height:{ideal:720}
            }
        });

        video.srcObject = stream;
        socket.emit('create_camera');
        stopBtn.disabled = false;

    } catch(e) {
        status('Ошибка камеры: ' + e.message);
        startBtn.disabled = false;
    }
};

stopBtn.onclick = () => {
    if (pc) {
        pc.close();
        pc = null;
    }

    if (stream) {
        stream.getTracks().forEach(t => t.stop());
        stream = null;
    }

    video.srcObject = null;
    socket.emit('stop_camera');

    document.getElementById('codeBox').style.display = 'none';

    stopBtn.disabled = true;
    startBtn.disabled = false;

    status('Камера выключена.');
};

window.addEventListener('beforeunload', () => {
    socket.emit('stop_camera');
});
</script></body></html>"""


VIEWER = """<!doctype html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>CameraTel — Viewer</title>
""" + STYLE + """
<script src="https://cdn.socket.io/4.7.5/socket.io.min.js"></script>
</head><body><main class="panel">

<h1>CameraTel / Viewer</h1>
<p class="sub">Зритель: {{username}}</p>

<label>Код камеры</label>
<input id="codeInput" placeholder="Введите код камеры" maxlength="12">

<button id="connectBtn">Подключиться</button>

<div class="status" id="status">
Введите код с телефона.
</div>

<video id="remoteVideo" autoplay playsinline controls></video>

<div class="row">
<button id="disconnectBtn" class="danger" disabled>
Отключиться
</button>
<a class="btn secondary" href="/logout">Выйти</a>
</div>

<p><a href="/">На главную</a></p>

</main>

<script>
const socket = io();

const video = document.getElementById('remoteVideo');
const statusEl = document.getElementById('status');
const connectBtn = document.getElementById('connectBtn');
const disconnectBtn = document.getElementById('disconnectBtn');

let pc = null;
let pendingIce = [];

const rtcConfig = {
    iceServers: [
        {urls:'stun:stun.l.google.com:19302'}
    ]
};

function status(text, live=false) {
    statusEl.textContent = text;
    statusEl.className = live ? 'status green' : 'status';
}

function makePeer() {
    pc = new RTCPeerConnection(rtcConfig);

    pc.ontrack = e => {
        video.srcObject = e.streams[0];
        video.play().catch(() => {});
        status('LIVE — вы смотрите трансляцию', true);
    };

    pc.onicecandidate = e => {
        if (e.candidate) {
            socket.emit('signal', {
                type:'ice',
                candidate:e.candidate
            });
        }
    };

    pc.onconnectionstatechange = () => {
        if (pc) {
            status('Соединение: ' + pc.connectionState,
                pc.connectionState === 'connected');
        }
    };
}

async function flushIce() {
    for (const candidate of pendingIce) {
        try {
            await pc.addIceCandidate(candidate);
        } catch(e) {
            console.error(e);
        }
    }
    pendingIce = [];
}

socket.on('joined_camera', () => {
    connectBtn.disabled = true;
    disconnectBtn.disabled = false;
    status('Код принят. Ожидаем видео...');
});

socket.on('signal', async data => {
    try {
        if (data.type === 'offer') {
            if (pc) pc.close();

            pendingIce = [];
            makePeer();

            await pc.setRemoteDescription(data.description);
            await flushIce();

            const answer = await pc.createAnswer();
            await pc.setLocalDescription(answer);

            socket.emit('signal', {
                type:'answer',
                description:pc.localDescription
            });

        } else if (data.type === 'ice' && data.candidate) {
            if (pc && pc.remoteDescription) {
                await pc.addIceCandidate(data.candidate);
            } else {
                pendingIce.push(data.candidate);
            }
        }

    } catch(e) {
        status('Ошибка WebRTC: ' + e.message);
        console.error(e);
    }
});

socket.on('join_error', data => {
    status(data.message);
    connectBtn.disabled = false;
});

socket.on('camera_stopped', () => {
    status('Владелец остановил трансляцию.');

    if (pc) {
        pc.close();
        pc = null;
    }

    pendingIce = [];
    video.srcObject = null;

    connectBtn.disabled = false;
    disconnectBtn.disabled = true;
});

socket.on('connect_error', e => {
    status('Ошибка сервера: ' + e.message);
});

connectBtn.onclick = () => {
    const code = document.getElementById('codeInput').value.trim();

    if (!code) {
        status('Введите код камеры.');
        return;
    }

    connectBtn.disabled = true;
    socket.emit('join_camera', {code:code});
};

disconnectBtn.onclick = () => {
    socket.emit('leave_camera');

    if (pc) {
        pc.close();
        pc = null;
    }

    pendingIce = [];
    video.srcObject = null;

    connectBtn.disabled = false;
    disconnectBtn.disabled = true;

    status('Вы отключились.');
};

window.addEventListener('beforeunload', () => {
    socket.emit('leave_camera');
});
</script></body></html>"""


@app.route("/")
def home():
    return render_template_string(HOME)


@app.route("/camera")
def camera():
    return render_template_string(CAMERA)


@app.route("/register", methods=["GET", "POST"])
def register():
    error = None

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if len(username) < 3 or len(username) > 32:
            error = "Логин должен содержать от 3 до 32 символов."

        elif len(password) < 8:
            error = "Пароль должен содержать минимум 8 символов."

        elif username.lower() in users:
            error = "Такой логин уже занят."

        else:
            users[username.lower()] = {
                "username": username,
                "password": generate_password_hash(password)
            }

            session["username"] = username
            return redirect(url_for("viewer"))

    return render_template_string(REGISTER, error=error)


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        user = users.get(username.lower())

        if user and check_password_hash(user["password"], password):
            session["username"] = user["username"]
            return redirect(url_for("viewer"))

        error = "Неверный логин или пароль."

    return render_template_string(LOGIN, error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/viewer")
@login_required
def viewer():
    return render_template_string(
        VIEWER,
        username=session["username"]
    )


def make_code():
    alphabet = string.ascii_letters + string.digits

    while True:
        code = "".join(secrets.choice(alphabet) for _ in range(7))

        if code not in rooms:
            return code


@socketio.on("create_camera")
def create_camera():
    old_code = sid_to_code.get(request.sid)

    if old_code:
        rooms.pop(old_code, None)

    code = make_code()

    rooms[code] = {
        "camera": request.sid,
        "viewer": None
    }

    sid_to_code[request.sid] = code

    emit("camera_created", {"code": code})


@socketio.on("join_camera")
def join_camera(data):
    if not session.get("username"):
        emit("join_error", {
            "message": "Сначала войдите в аккаунт."
        })
        return

    code = (data or {}).get("code", "").strip()
    room = rooms.get(code)

    if not room:
        emit("join_error", {
            "message": "Код не найден или камера отключена."
        })
        return

    if room["viewer"] and room["viewer"] != request.sid:
        emit("join_error", {
            "message": "К этой камере уже подключён другой зритель."
        })
        return

    room["viewer"] = request.sid
    sid_to_code[request.sid] = code

    socketio.emit("viewer_joined", {}, to=room["camera"])
    emit("joined_camera", {"ok": True})


@socketio.on("signal")
def relay_signal(data):
    code = sid_to_code.get(request.sid)
    room = rooms.get(code) if code else None

    if not room:
        return

    if request.sid == room["camera"]:
        target = room["viewer"]
    elif request.sid == room["viewer"]:
        target = room["camera"]
    else:
        return

    if target:
        socketio.emit("signal", data, to=target)


@socketio.on("leave_camera")
def leave_camera():
    code = sid_to_code.pop(request.sid, None)
    room = rooms.get(code) if code else None

    if not room:
        return

    if request.sid == room["viewer"]:
        room["viewer"] = None
        socketio.emit("viewer_left", {}, to=room["camera"])

    elif request.sid == room["camera"]:
        if room["viewer"]:
            socketio.emit("camera_stopped", {}, to=room["viewer"])

        rooms.pop(code, None)


@socketio.on("stop_camera")
def stop_camera():
    leave_camera()


@socketio.on("disconnect")
def on_disconnect():
    leave_camera()


if __name__ == "__main__":
    socketio.run(
        app,
        host="0.0.0.0",
        port=5000,
        allow_unsafe_werkzeug=True
    )
