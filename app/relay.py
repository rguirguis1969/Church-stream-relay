#!/usr/bin/env python3
"""Forward one room's incoming OBS stream to one destination.

nginx-rtmp starts one copy of this per destination slot when OBS goes live
(exec_push), and restarts it automatically a few seconds after it exits.
So if YouTube or Facebook hiccups, that destination reconnects on its own
and the others are not affected.

Usage: relay.py <obs-stream-key> <slot>
"""
import os
import signal
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (LOG_DIR, RUN_DIR, full_target, load_config,  # noqa: E402
                    log_path, pid_path, room_by_key)

child = None
pidfile = None


def cleanup():
    if pidfile:
        try:
            os.unlink(pidfile)
        except OSError:
            pass


def stop(signum, frame):
    if child and child.poll() is None:
        child.terminate()
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
    cleanup()
    sys.exit(0)


def idle():
    # Nothing to send for this slot. Wait until the stream ends (nginx stops
    # us then) instead of exiting, so nginx doesn't restart us every few seconds.
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    stream_key, slot = sys.argv[1], sys.argv[2]
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    os.makedirs(RUN_DIR, exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)

    cfg = load_config()
    room_id = room_by_key(cfg, stream_key)
    if not room_id:
        idle()
    pidfile = pid_path(room_id, slot)
    with open(pidfile, "w") as f:
        f.write(str(os.getpid()))

    room = cfg["rooms"][room_id]
    dest = room["destinations"].get(slot, {})
    target = full_target(dest)
    if not dest.get("enabled") or not target:
        idle()

    source = "rtmp://127.0.0.1:1935/live/" + stream_key
    cmd = [
        "ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "warning",
        "-rw_timeout", "15000000",
        "-i", source,
        "-map", "0", "-c", "copy",
        "-f", "flv", target,
    ]
    lp = log_path(room_id, slot)
    try:
        if os.path.getsize(lp) > 1_000_000:
            os.replace(lp, lp + ".old")
    except OSError:
        pass
    with open(lp, "a") as log:
        log.write("\n=== %s  connecting to %s ===\n"
                  % (time.strftime("%Y-%m-%d %H:%M:%S"), dest.get("label", slot)))
        log.flush()
        child = subprocess.Popen(cmd, stdout=log, stderr=log)
        code = child.wait()
        log.write("=== %s  connection ended (code %s), retrying in a few seconds ===\n"
                  % (time.strftime("%Y-%m-%d %H:%M:%S"), code))
    cleanup()
    sys.exit(1)
