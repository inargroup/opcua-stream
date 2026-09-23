"""Sink / receiver backend + Socket.IO test suite.

Covers:
- /api/sink start/stop/status
- Full transmission loop feeds sink -> frames_received increments, tag_count grows
- /api/sink/tags returns tags with growing sample_count
- Dynamic tag adaptation: adding a new source tag surfaces on sink within ~4s
- Socket.IO 'sink_frame' + 'sink_stats' events, initial 'sink_stats' on connect
"""
import os
import time
from urllib.parse import urlparse

import pytest
import requests
import socketio
from dotenv import load_dotenv

load_dotenv("/app/frontend/.env")
BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"
WS_ORIGIN = BASE_URL
SINK_PORT = 9800


@pytest.fixture(scope="module")
def s():
    sess = requests.Session()
    yield sess
    # teardown: stop runtime + sink
    try:
        sess.post(f"{API}/runtime/stop", timeout=10)
        sess.post(f"{API}/sink/stop", timeout=10)
    except Exception:
        pass


def _ensure_stopped(s):
    s.post(f"{API}/runtime/stop", timeout=10)
    s.post(f"{API}/sink/stop", timeout=10)
    time.sleep(0.3)


def test_sink_start_status_stop(s):
    _ensure_stopped(s)
    r = s.post(f"{API}/sink/start", json={"port": SINK_PORT}, timeout=15)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["running"] is True
    assert d["port"] == SINK_PORT
    assert d["opcua_endpoint"].startswith("opc.tcp://127.0.0.1:4841")

    r = s.get(f"{API}/sink", timeout=10)
    assert r.status_code == 200
    st = r.json()
    for k in ("running", "port", "opcua_endpoint", "frames_received",
              "bytes_received", "fps", "bps", "tag_count", "last_seq", "uptime"):
        assert k in st, f"missing key {k}"
    assert st["running"] is True

    r = s.post(f"{API}/sink/stop", timeout=10)
    assert r.status_code == 200 and r.json()["running"] is False


def test_full_loop_frames_and_tags(s):
    _ensure_stopped(s)
    assert s.post(f"{API}/sink/start", json={"port": SINK_PORT}, timeout=15).status_code == 200
    assert s.post(f"{API}/runtime/start", json={"format": "json"}, timeout=10).status_code == 200

    time.sleep(3.0)
    st = s.get(f"{API}/sink").json()
    assert st["frames_received"] > 0, f"no frames received: {st}"
    assert st["bytes_received"] > 0
    assert st["tag_count"] >= 5, f"tag_count too low: {st['tag_count']}"

    tags = s.get(f"{API}/sink/tags").json()
    assert isinstance(tags, list) and len(tags) >= 5
    sample = tags[0]
    for k in ("name", "value", "quality", "sample_count", "first_seen", "last_update"):
        assert k in sample
    assert sample["quality"] == 192
    first_sc = sample["sample_count"]

    time.sleep(1.5)
    tags2 = s.get(f"{API}/sink/tags").json()
    same = next(t for t in tags2 if t["name"] == sample["name"])
    assert same["sample_count"] > first_sc, "sample_count not growing"


def test_dynamic_tag_adaptation(s):
    # sink + runtime already running from prior test; ensure so
    if not s.get(f"{API}/sink").json()["running"]:
        s.post(f"{API}/sink/start", json={"port": SINK_PORT}, timeout=15)
    if not s.get(f"{API}/runtime").json()["active"]:
        s.post(f"{API}/runtime/start", json={"format": "json"}, timeout=10)

    # Pick a variable not currently added: check current tags first
    existing_tags = s.get(f"{API}/tags").json()
    existing_names = {t["name"] for t in existing_tags if t["server_id"] == "demo-server"}

    # Browse Plant for candidates
    br = s.get(f"{API}/servers/demo-server/browse", params={"node_id": "ns=2;s=Plant"}).json()
    candidates = [n for n in br["nodes"] if n.get("is_variable") and n["name"] not in existing_names]
    assert candidates, f"no unused variables to add (existing: {existing_names})"
    pick = candidates[0]
    payload = {
        "server_id": "demo-server",
        "node_id": pick["node_id"],
        "name": f"TEST_dyn_{pick['name']}",
        "data_type": pick.get("data_type", "Double"),
        "unit": "x",
        "sampling_interval": 200,
    }
    r = s.post(f"{API}/tags", json=payload, timeout=10)
    assert r.status_code == 200, r.text
    tag_id = r.json()["id"]

    try:
        # transmitter hot-reloads every 2s; wait up to 8s
        target = payload["name"]
        found = False
        deadline = time.time() + 10
        while time.time() < deadline:
            names = {t["name"] for t in s.get(f"{API}/sink/tags").json()}
            if target in names:
                found = True
                break
            time.sleep(0.5)
        assert found, f"new tag {target} not surfaced on sink within 10s"
    finally:
        s.delete(f"{API}/tags/{tag_id}", timeout=10)


def test_ws_sink_frame_and_stats(s):
    _ensure_stopped(s)
    assert s.post(f"{API}/sink/start", json={"port": SINK_PORT}, timeout=15).status_code == 200

    frames, stats = [], []
    c = socketio.Client(reconnection=False, logger=False, engineio_logger=False)

    @c.on("sink_frame")
    def on_frame(d):
        frames.append(d)

    @c.on("sink_stats")
    def on_stats(d):
        stats.append(d)

    c.connect(WS_ORIGIN, socketio_path="/api/socket.io", transports=["websocket"], wait_timeout=10)
    time.sleep(0.8)
    # initial sink_stats emitted on connect
    assert len(stats) >= 1, "no initial sink_stats received"

    s.post(f"{API}/runtime/start", json={"format": "json"}, timeout=10)
    time.sleep(3.0)
    s.post(f"{API}/runtime/stop", timeout=10)
    c.disconnect()

    assert len(frames) > 0, "no sink_frame events received"
    f = frames[0]
    for k in ("seq", "ts", "format", "byte_size", "tag_count", "samples", "new_tags"):
        assert k in f, f"missing key {k} in sink_frame: {f}"
    assert isinstance(f["samples"], list) and len(f["samples"]) >= 1
    sm = f["samples"][0]
    for k in ("name", "value", "quality", "is_new"):
        assert k in sm
    assert sm["quality"] == 192
    # at least one stats emission after connect
    assert len(stats) >= 2, f"expected multiple sink_stats, got {len(stats)}"

    s.post(f"{API}/sink/stop", timeout=10)
