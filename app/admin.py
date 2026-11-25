#!/usr/bin/env python3
"""Password-protected settings page for the stream relay.

Also answers nginx-rtmp's "is this stream key allowed?" question, so only
OBS with the secret stream key can send video to the server.
"""
import hmac
import os
import re
import secrets
import signal
import time
import urllib.request
import xml.etree.ElementTree as ET

from flask import (Flask, abort, flash, redirect, render_template, request,
                   session, url_for)

from common import (DATA_DIR, SLOTS, full_target, load_config, log_path,
                    new_ingest_key, new_room, pid_path, room_by_key,
                    room_id_for, save_config)

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
URL_PREFIX = "/" + os.environ.get("URL_PREFIX", "").strip("/")
URL_PREFIX = "" if URL_PREFIX == "/" else URL_PREFIX
PUBLIC_HOST = os.environ.get("PUBLIC_HOST", "").strip()
RTMP_PORT = os.environ.get("RTMP_PORT", "1935").strip()
STAT_URL = "http://127.0.0.1:8091/stat"


def secret_key():
    path = os.path.join(DATA_DIR, "session.secret")
    try:
        with open(path) as f:
            return f.read().strip()
    except FileNotFoundError:
        key = secrets.token_hex(32)
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(path, "w") as f:
            f.write(key)
        os.chmod(path, 0o600)
        return key


app = Flask(__name__)
app.secret_key = secret_key()
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "") == "1",
    PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 30,
)


class PrefixMiddleware:
    """Lets the page live under a sub-path such as /relay behind a proxy."""

    def __init__(self, wsgi_app, prefix):
        self.wsgi_app, self.prefix = wsgi_app, prefix

    def __call__(self, environ, start_response):
        path = environ.get("PATH_INFO", "")
        if self.prefix:
            if path.startswith(self.prefix):
                environ["PATH_INFO"] = path[len(self.prefix):] or "/"
            environ["SCRIPT_NAME"] = self.prefix
        return self.wsgi_app(environ, start_response)


app.wsgi_app = PrefixMiddleware(app.wsgi_app, URL_PREFIX)

# ---------------------------------------------------------------- login ---
_failures = {}  # ip -> [count, first_failure_time]


def too_many_failures(ip):
    count, first = _failures.get(ip, (0, 0))
    if time.time() - first > 15 * 60:
        _failures.pop(ip, None)
        return False
    return count >= 10


def logged_in():
    return session.get("ok") is True


@app.before_request
def guard():
    if request.endpoint in ("login", "static", "hook_publish", "hook_done"):
        return
    if not logged_in():
        return redirect(url_for("login"))
    if request.method == "POST":
        token = request.form.get("csrf", "")
        if not hmac.compare_digest(token, session.get("csrf", "")):
            abort(400)


@app.context_processor
def inject():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return {"csrf": session["csrf"]}


@app.route("/login", methods=["GET", "POST"])
def login():
    if not ADMIN_PASSWORD:
        return "ADMIN_PASSWORD is not set. See the setup guide.", 500
    error = None
    if request.method == "POST":
        ip = request.remote_addr
        if too_many_failures(ip):
            error = "Too many wrong attempts. Please wait 15 minutes."
        elif hmac.compare_digest(request.form.get("password", "").encode(),
                                 ADMIN_PASSWORD.encode()):
            _failures.pop(ip, None)
            session.clear()
            session.permanent = True
            session["ok"] = True
            return redirect(url_for("index"))
        else:
            time.sleep(1)
            count, first = _failures.get(ip, (0, time.time()))
            _failures[ip] = (count + 1, first)
            error = "That password isn't right."
    return render_template("login.html", error=error)


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


# -------------------------------------------------- nginx-rtmp callbacks ---
def from_localhost():
    return request.remote_addr in ("127.0.0.1", "::1")


@app.route("/hook/publish", methods=["POST"])
def hook_publish():
    if not from_localhost():
        abort(404)
    if room_by_key(load_config(), request.form.get("name", "")):
        return "ok"
    app.logger.warning("Rejected a stream with the wrong key from %s",
                       request.form.get("addr", "?"))
    return "wrong key", 403


@app.route("/hook/done", methods=["POST"])
def hook_done():
    if not from_localhost():
        abort(404)
    return "ok"


# ----------------------------------------------------------------- status ---
def incoming_status(cfg):
    """Which rooms have OBS connected right now, and at what bitrate?"""
    live = {}
    try:
        with urllib.request.urlopen(STAT_URL, timeout=2) as r:
            root = ET.fromstring(r.read())
    except Exception:
        return live
    for stream in root.iter("stream"):
        if stream.find("publishing") is None:
            continue
        rid = room_by_key(cfg, stream.findtext("name", ""))
        if rid:
            bw = int(stream.findtext("bw_in", "0") or 0)
            secs = int(stream.findtext("time", "0") or 0) // 1000
            live[rid] = {"kbps": bw // 1000, "duration": fmt_duration(secs)}
    return live


def worker_pid(rid, slot):
    try:
        with open(pid_path(rid, slot)) as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)
        return pid
    except (OSError, ValueError):
        return None


def mask(text, cfg):
    secrets_ = []
    for room in cfg["rooms"].values():
        secrets_.append(room["ingest_key"])
        secrets_ += [d.get("key", "") for d in room["destinations"].values()]
    for value in secrets_:
        if value and len(value) > 3:
            text = text.replace(value, "****")
    # Facebook keys carry extra query parameters; hide anything after "?".
    return re.sub(r"\?[^\s'\"]+", "?****", text)


def recent_log(rid, slot, cfg, lines=12):
    try:
        with open(log_path(rid, slot), errors="replace") as f:
            tail = f.readlines()[-lines:]
    except FileNotFoundError:
        return ""
    return mask("".join(tail), cfg)


def fmt_duration(s):
    h, m = divmod(s // 60, 60)
    return "%dh %02dm" % (h, m) if h else "%d min" % m


def server_host():
    if PUBLIC_HOST:
        return PUBLIC_HOST
    host = request.host
    if host.startswith("["):  # IPv6 literal
        return host.split("]")[0] + "]"
    return host.rsplit(":", 1)[0]


def get_room(cfg, rid):
    room = cfg["rooms"].get(rid)
    if not room:
        abort(404)
    return room


def restart_worker(rid, slot):
    """Stop a destination's forwarder; nginx restarts it with the new settings."""
    pid = worker_pid(rid, slot)
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
            return True
        except OSError:
            pass
    return False


# ------------------------------------------------------------------ pages ---
@app.route("/")
def index():
    cfg = load_config()
    live = incoming_status(cfg)
    rooms = []
    for rid, room in cfg["rooms"].items():
        dests = []
        for slot in SLOTS:
            d = room["destinations"][slot]
            if not d.get("enabled"):
                state = "off"
            elif not full_target(d):
                state = "incomplete"
            elif rid not in live:
                state = "ready"
            else:
                state = "sending"
            dests.append({"slot": slot, "d": d, "state": state,
                          "log": recent_log(rid, slot, cfg) if d.get("enabled") else ""})
        rooms.append({"id": rid, "room": room, "live": live.get(rid), "dests": dests})
    port = "" if RTMP_PORT == "1935" else ":" + RTMP_PORT
    obs_server = "rtmp://%s%s/live" % (server_host(), port)
    return render_template("index.html", rooms=rooms, obs_server=obs_server,
                           open_room=request.args.get("room"))


def back(rid=None):
    return redirect(url_for("index", room=rid) + ("#" + rid if rid else ""))


@app.route("/room/<rid>/save", methods=["POST"])
def save(rid):
    cfg = load_config()
    room = get_room(cfg, rid)
    before = {s: dict(room["destinations"][s]) for s in SLOTS}
    name = request.form.get("name", "").strip()[:40]
    if name:
        room["name"] = name
    for slot in SLOTS:
        d = room["destinations"][slot]
        url = request.form.get(slot + "_url", "").strip()
        if url and not re.match(r"^rtmps?://", url):
            flash("The server address for %s must start with rtmp:// or rtmps://"
                  % d["label"], "error")
            return back(rid)
        d["url"] = url
        d["enabled"] = request.form.get(slot + "_enabled") == "on"
        key = request.form.get(slot + "_key", "").strip()
        if key:  # blank means "keep the current key"
            d["key"] = key
        if request.form.get(slot + "_clear") == "on":
            d["key"] = ""
            d["enabled"] = False
        if slot == "extra":
            d["label"] = request.form.get("extra_label", "").strip()[:40] or "Other"
    save_config(cfg)
    changed = [s for s in SLOTS if room["destinations"][s] != before[s]]
    restarted = [s for s in changed if restart_worker(rid, s)]
    msg = "%s saved." % room["name"]
    if restarted:
        msg += " This room is live, so the changed destinations will reconnect in a few seconds."
    flash(msg, "ok")
    return back(rid)


@app.route("/room/<rid>/reconnect", methods=["POST"])
def reconnect(rid):
    cfg = load_config()
    room = get_room(cfg, rid)
    slot = request.form.get("slot", "")
    if slot in SLOTS and restart_worker(rid, slot):
        flash("Reconnecting %s for %s. Give it about 10 seconds."
              % (room["destinations"][slot]["label"], room["name"]), "ok")
    else:
        flash("Nothing to reconnect right now.", "error")
    return back(rid)


@app.route("/room/<rid>/new-key", methods=["POST"])
def new_key(rid):
    cfg = load_config()
    room = get_room(cfg, rid)
    room["ingest_key"] = new_ingest_key()
    save_config(cfg)
    flash("New OBS stream key created for %s. Copy it into that room's OBS before "
          "the next stream. The old key no longer works." % room["name"], "ok")
    return back(rid)


@app.route("/room/add", methods=["POST"])
def add_room():
    cfg = load_config()
    name = request.form.get("name", "").strip()[:40]
    if not name:
        flash("Give the new room a name.", "error")
        return back()
    rid = room_id_for(name, cfg["rooms"])
    cfg["rooms"][rid] = new_room(name)
    save_config(cfg)
    flash("Added %s." % name, "ok")
    return back(rid)


@app.route("/room/<rid>/delete", methods=["POST"])
def delete_room(rid):
    cfg = load_config()
    room = get_room(cfg, rid)
    if rid in incoming_status(cfg):
        flash("%s is live right now. Stop streaming before removing it." % room["name"], "error")
        return back(rid)
    if request.form.get("confirm") != room["name"]:
        flash("To remove a room, type its name exactly in the box.", "error")
        return back(rid)
    del cfg["rooms"][rid]
    save_config(cfg)
    flash("Removed %s." % room["name"], "ok")
    return back()


if __name__ == "__main__":
    from waitress import serve
    opts = {}
    if os.environ.get("TRUSTED_PROXY"):
        # Behind our own reverse proxy: take the visitor's real IP and scheme from it.
        opts = dict(trusted_proxy=os.environ["TRUSTED_PROXY"], trusted_proxy_count=1,
                    trusted_proxy_headers={"x-forwarded-for", "x-forwarded-proto",
                                           "x-forwarded-host"},
                    clear_untrusted_proxy_headers=True)
    serve(app, host="0.0.0.0", port=8080, threads=6, ident=None, **opts)
