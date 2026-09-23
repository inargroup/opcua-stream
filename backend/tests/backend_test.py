"""OPC UA client backend + Socket.IO test suite.

Covers:
- Server CRUD + connect/disconnect
- Browse address space (Plant folder + variables)
- Tag CRUD (duplicate 409)
- Runtime start/format/stop
- Socket.IO connection lifecycle, initial stats, frame events (json vs msgpack)
- Negative WS path
Note: this app has no rooms, no auth, no multi-user collab.
"""
import asyncio
import json
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

# Build ws url from https base
_p = urlparse(BASE_URL)
WS_ORIGIN = BASE_URL  # python-socketio handles https/wss transparently


# ---------- fixtures ----------
@pytest.fixture(scope="module")
def s():
    return requests.Session()


# ---------- Servers ----------
def test_demo_server_present_and_connected(s):
    r = s.get(f"{API}/servers", timeout=15)
    assert r.status_code == 200
    servers = r.json()
    demo = next((x for x in servers if x["id"] == "demo-server"), None)
    assert demo is not None, f"demo-server missing. servers={servers}"
    assert demo["status"]["connected"] is True
    assert demo["tag_count"] == 5


def test_server_crud_and_bad_connect(s):
    # create
    payload = {"name": "TEST_bad", "endpoint": "opc.tcp://127.0.0.1:59999", "security_policy": "None"}
    r = s.post(f"{API}/servers", json=payload, timeout=10)
    assert r.status_code == 200, r.text
    sid = r.json()["id"]

    # update
    r = s.put(f"{API}/servers/{sid}", json={"name": "TEST_bad2"}, timeout=10)
    assert r.status_code == 200 and r.json()["name"] == "TEST_bad2"

    # connect to unreachable -> 502
    r = s.post(f"{API}/servers/{sid}/connect", timeout=20)
    assert r.status_code == 502, f"expected 502, got {r.status_code}: {r.text}"

    # delete
    r = s.delete(f"{API}/servers/{sid}", timeout=10)
    assert r.status_code == 200


# ---------- Browse ----------
def test_browse_root_and_plant(s):
    r = s.get(f"{API}/servers/demo-server/browse", timeout=15)
    assert r.status_code == 200
    nodes = r.json()["nodes"]
    plant = next((n for n in nodes if n["name"] == "Plant"), None)
    assert plant is not None, f"Plant folder missing. nodes={[n['name'] for n in nodes]}"

    # descend
    r2 = s.get(f"{API}/servers/demo-server/browse", params={"node_id": plant["node_id"]}, timeout=15)
    assert r2.status_code == 200
    children = r2.json()["nodes"]
    variables = [n for n in children if n.get("is_variable")]
    names = {v["name"] for v in variables}
    expected = {"Temperature", "Pressure", "FlowRate", "MotorSpeed", "TankLevel",
                "Vibration", "PowerConsumption", "ValvePosition", "PumpStatus",
                "ProductionCount", "QualityIndex"}
    assert expected.issubset(names), f"missing vars: {expected - names}"
    assert len(variables) == 11
    for v in variables:
        assert v.get("value") is not None
        assert v.get("data_type") not in (None, "Unknown")


# ---------- Tags ----------
def test_tag_crud_and_duplicate(s):
    tags = s.get(f"{API}/tags").json()
    demo_tags = [t for t in tags if t["server_id"] == "demo-server"]
    assert len(demo_tags) >= 5

    # duplicate
    existing = demo_tags[0]
    dup = {"server_id": "demo-server", "node_id": existing["node_id"], "name": "TEST_dup", "sampling_interval": 500}
    r = s.post(f"{API}/tags", json=dup, timeout=10)
    assert r.status_code == 409

    # create new via a valid variable (Vibration)
    br = s.get(f"{API}/servers/demo-server/browse", params={"node_id": "ns=2;s=Plant"}).json()
    vib = next(n for n in br["nodes"] if n["name"] == "Vibration")
    payload = {"server_id": "demo-server", "node_id": vib["node_id"], "name": "TEST_Vibration",
               "data_type": vib.get("data_type", "Double"), "unit": "mm/s", "sampling_interval": 300}
    r = s.post(f"{API}/tags", json=payload, timeout=10)
    assert r.status_code == 200, r.text
    tag_id = r.json()["id"]

    # update
    r = s.put(f"{API}/tags/{tag_id}", json={"sampling_interval": 400}, timeout=10)
    assert r.status_code == 200 and r.json()["sampling_interval"] == 400

    # delete
    r = s.delete(f"{API}/tags/{tag_id}", timeout=10)
    assert r.status_code == 200


# ---------- Runtime ----------
def test_runtime_start_switch_stop(s):
    # ensure stopped
    s.post(f"{API}/runtime/stop", timeout=10)

    r = s.post(f"{API}/runtime/start", json={"format": "json"}, timeout=10)
    assert r.status_code == 200
    assert r.json()["active"] is True

    time.sleep(2.0)
    rt = s.get(f"{API}/runtime").json()
    assert rt["frames_total"] > 0
    assert rt["bytes_total"] > 0
    assert rt["fps"] > 0

    # switch format
    r = s.post(f"{API}/runtime/format", json={"format": "msgpack"}, timeout=10)
    assert r.status_code == 200 and r.json()["format"] == "msgpack"

    time.sleep(1.0)
    r = s.post(f"{API}/runtime/stop", timeout=10)
    assert r.status_code == 200
    assert r.json()["active"] is False
    assert r.json()["uptime"] == 0


# ---------- Socket.IO ----------
class _Collector:
    def __init__(self):
        self.stats = []
        self.frames = []
        self.connected = False


def _make_client():
    return socketio.Client(reconnection=False, logger=False, engineio_logger=False)


def test_ws_connect_and_initial_stats():
    c = _make_client()
    col = _Collector()

    @c.event
    def connect():
        col.connected = True

    @c.on("stats")
    def on_stats(data):
        col.stats.append(data)

    c.connect(WS_ORIGIN, socketio_path="/api/socket.io", transports=["websocket"], wait_timeout=10)
    time.sleep(1.0)
    assert col.connected
    assert len(col.stats) >= 1
    assert "active" in col.stats[0]
    c.disconnect()


def test_ws_wrong_path_fails():
    c = _make_client()
    with pytest.raises(Exception):
        c.connect(WS_ORIGIN, socketio_path="/api/wrongpath", transports=["websocket"], wait_timeout=5)


def test_ws_frames_json_vs_msgpack_size():
    s = requests.Session()
    s.post(f"{API}/runtime/stop", timeout=10)

    # JSON pass
    c = _make_client()
    col = _Collector()
    @c.on("frame")
    def on_frame(data):
        col.frames.append(data)
    @c.on("stats")
    def on_stats(data):
        col.stats.append(data)

    c.connect(WS_ORIGIN, socketio_path="/api/socket.io", transports=["websocket"], wait_timeout=10)
    s.post(f"{API}/runtime/start", json={"format": "json"}, timeout=10)
    time.sleep(3.0)
    s.post(f"{API}/runtime/stop", timeout=10)
    json_frames = list(col.frames)
    json_stats = list(col.stats)
    col.frames.clear(); col.stats.clear()

    # msgpack pass
    s.post(f"{API}/runtime/start", json={"format": "msgpack"}, timeout=10)
    time.sleep(3.0)
    s.post(f"{API}/runtime/stop", timeout=10)
    mp_frames = list(col.frames)
    c.disconnect()

    assert len(json_frames) > 0, "no json frames received"
    assert len(mp_frames) > 0, "no msgpack frames received"
    assert len(json_stats) >= 1, "no periodic stats"

    # validate frame shape
    f = json_frames[0]
    for k in ("seq", "ts", "format", "byte_size", "tag_count", "samples", "preview"):
        assert k in f, f"missing key {k}"
    assert f["format"] == "json"
    assert f["tag_count"] >= 1
    assert isinstance(f["samples"], list) and len(f["samples"]) >= 1
    sample = f["samples"][0]
    assert sample["quality"] == 192

    mf = mp_frames[0]
    assert mf["format"] == "msgpack"

    # msgpack should on average be smaller for same tag set
    avg_json = sum(x["byte_size"] for x in json_frames) / len(json_frames)
    avg_mp = sum(x["byte_size"] for x in mp_frames) / len(mp_frames)
    assert avg_mp < avg_json, f"msgpack ({avg_mp}) not smaller than json ({avg_json})"


def test_ws_rapid_reconnect():
    for _ in range(3):
        c = _make_client()
        c.connect(WS_ORIGIN, socketio_path="/api/socket.io", transports=["websocket"], wait_timeout=10)
        time.sleep(0.3)
        c.disconnect()
