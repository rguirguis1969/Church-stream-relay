"""Shared helpers for the settings page and the relay workers."""
import copy
import json
import os
import re
import secrets
import tempfile

DATA_DIR = os.environ.get("DATA_DIR", "/data")
RUN_DIR = os.environ.get("RUN_DIR", "/run/relay")
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")
LOG_DIR = os.path.join(DATA_DIR, "logs")

# Each room (e.g. Main sanctuary, Chapel) has its own OBS stream key and these
# destination slots. Every slot gets its own forwarding process, so if one
# platform drops, the others keep going.
SLOTS = ["youtube", "facebook", "extra"]

DEFAULT_DESTINATIONS = {
    "youtube": {
        "label": "YouTube",
        "url": "rtmp://a.rtmp.youtube.com/live2",
        "key": "",
        "enabled": False,
    },
    "facebook": {
        "label": "Facebook",
        # Facebook only accepts secure RTMPS, which ffmpeg handles directly.
        "url": "rtmps://live-api-s.facebook.com:443/rtmp",
        "key": "",
        "enabled": False,
    },
    "extra": {
        "label": "Other",
        "url": "",
        "key": "",
        "enabled": False,
    },
}

DEFAULT_ROOMS = ["Main sanctuary", "Chapel"]


def new_ingest_key():
    return "live-" + secrets.token_urlsafe(18)


def new_room(name):
    return {
        "name": name,
        "ingest_key": new_ingest_key(),
        "destinations": copy.deepcopy(DEFAULT_DESTINATIONS),
    }


def room_id_for(name, existing):
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:30] or "room"
    rid, n = base, 2
    while rid in existing:
        rid, n = "%s-%d" % (base, n), n + 1
    return rid


def default_config():
    rooms = {}
    for name in DEFAULT_ROOMS:
        rooms[room_id_for(name, rooms)] = new_room(name)
    return {"rooms": rooms}


def load_config():
    try:
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
    except (FileNotFoundError, ValueError):
        cfg = default_config()
        save_config(cfg)
        return cfg
    changed = False
    for room in cfg.setdefault("rooms", {}).values():
        if not room.get("ingest_key"):
            room["ingest_key"] = new_ingest_key()
            changed = True
        dests = room.setdefault("destinations", {})
        for slot in SLOTS:
            if slot not in dests:
                dests[slot] = copy.deepcopy(DEFAULT_DESTINATIONS[slot])
                changed = True
    if changed:
        save_config(cfg)
    return cfg


def save_config(cfg):
    os.makedirs(DATA_DIR, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=DATA_DIR, prefix=".config-")
    with os.fdopen(fd, "w") as f:
        json.dump(cfg, f, indent=2)
    os.chmod(tmp, 0o600)
    os.replace(tmp, CONFIG_PATH)


def room_by_key(cfg, key):
    """Find the room whose OBS stream key matches (constant-time compare)."""
    import hmac
    found = None
    for rid, room in cfg["rooms"].items():
        if hmac.compare_digest(room["ingest_key"].encode(), key.encode()):
            found = rid
    return found


def full_target(dest):
    """Join the server URL and stream key the way OBS/Restream do."""
    url = (dest.get("url") or "").strip().rstrip("/")
    key = (dest.get("key") or "").strip()
    if not url or not key:
        return ""
    return url + "/" + key


def pid_path(room_id, slot):
    return os.path.join(RUN_DIR, "%s.%s.pid" % (room_id, slot))


def log_path(room_id, slot):
    return os.path.join(LOG_DIR, "%s.%s.log" % (room_id, slot))
