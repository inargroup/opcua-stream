"""Serial-link Sender -> Receiver tests (socat pair /tmp/ttyV0 <-> /tmp/ttyV1).

Covers: /api/serial/ports, sink start validation, runtime streaming over serial (json + msgpack),
dormancy on stop, revival on restart (no duplicate tags), sink_frame 'revived' socket events,
external OPC UA client read of sink nodes + StatusCodes, runtime start without serial.
"""
import asyncio
import os
import time

import pytest
import requests
import socketio
from dotenv import load_dotenv

load_dotenv("/app/frontend/.env")
BASE_URL = os.environ["REACT_APP_BACKEND_URL"].rstrip("/")
API = f"{BASE_URL}/api"
TX, RX = "/tmp/ttyV0", "/tmp/ttyV1"
SINK_EP = "opc.tcp://127.0.0.1:4841/emergent/sink/"


@pytest.fixture(scope="module")
def s():
    sess = requests.Session()
    sess.post(f"{API}/runtime/stop", timeout=10)
    sess.post(f"{API}/sink/stop", timeout=10)
    yield sess
    sess.post(f"{API}/runtime/stop", timeout=10)


def _wait(pred, timeout=8, step=0.3):
    end = time.time() + timeout
    while time.time() < end:
        v = pred()
        if v:
            return v
        time.sleep(step)
    return pred()


# --- serial ports listing
def test_serial_ports(s):
    d = s.get(f"{API}/serial/ports", timeout=10).json()
    assert isinstance(d["ports"], list)
    assert d["baud_rates"][0] == 9600 and d["baud_rates"][-1] == 2000000
    assert 115200 in d["baud_rates"]
    assert "settings" in d


# --- sink start validation
def test_sink_invalid_port_and_baud(s):
    r = s.post(f"{API}/sink/start", json={"serial_port": "/dev/doesnotexist", "baudrate": 115200}, timeout=10)
    assert r.status_code in (409, 502), r.text
    r = s.post(f"{API}/sink/start", json={"serial_port": RX, "baudrate": 1234}, timeout=10)
    assert r.status_code == 400, r.text
    r = s.post(f"{API}/sink/start", json={"serial_port": "", "baudrate": 115200}, timeout=10)
    print("empty port sink start:", r.status_code, r.text[:200])
    assert r.status_code in (400, 409, 422, 502)
    assert s.get(f"{API}/sink", timeout=10).json()["running"] is False


def test_runtime_invalid(s):
    r = s.post(f"{API}/runtime/start", json={"format": "json", "serial_port": "/dev/doesnotexist", "baudrate": 115200}, timeout=10)
    assert r.status_code in (409, 502)
    r = s.post(f"{API}/runtime/start", json={"format": "json", "serial_port": TX, "baudrate": 1234}, timeout=10)
    assert r.status_code == 400
    assert s.get(f"{API}/runtime", timeout=10).json()["active"] is False


# --- runtime without serial (local only)
def test_runtime_local_only(s):
    r = s.post(f"{API}/runtime/start", json={"format": "json"}, timeout=10)
    assert r.status_code == 200, r.text
    assert r.json()["active"] is True and r.json()["serial_port"] is None
    time.sleep(1.5)
    assert s.get(f"{API}/runtime", timeout=10).json()["frames_total"] > 0
    s.post(f"{API}/runtime/stop", timeout=10)


# --- full stream / dormancy / revive cycle
def test_stream_dormant_revive_cycles(s):
    r = s.post(f"{API}/sink/start", json={"serial_port": RX, "baudrate": 115200}, timeout=15)
    assert r.status_code == 200, r.text
    assert r.json()["running"] and r.json()["serial_connected"]

    events = {"revived": set(), "new": set(), "frames": 0}
    sio = socketio.Client(reconnection=False)

    @sio.on("sink_frame")
    def _f(d):
        events["frames"] += 1
        events["revived"].update(d.get("revived", []))
        events["new"].update(d.get("new_tags", []))

    sio.connect(BASE_URL, socketio_path="/api/socket.io", transports=["websocket"])
    try:
        expected = None
        for i, fmt in enumerate(["json", "msgpack", "json", "msgpack"]):
            r = s.post(f"{API}/runtime/start", json={"format": fmt, "serial_port": TX, "baudrate": 115200}, timeout=10)
            assert r.status_code == 200, r.text
            assert r.json()["serial_connected"] is True
            st = _wait(lambda: (lambda d: d if d["frames_received"] > 5 and d["dormant_count"] == 0 and d["tag_count"] > 0 else None)(s.get(f"{API}/sink", timeout=10).json()), timeout=15)
            assert st, f"cycle {i}: sink did not become active: {s.get(f'{API}/sink').json()}"
            assert st["crc_errors"] == 0
            if expected is None:
                expected = st["tag_count"]
            assert st["tag_count"] == expected, f"cycle {i} duplicate tags: {st['tag_count']} vs {expected}"
            tags = s.get(f"{API}/sink/tags", timeout=10).json()
            assert len(tags) == expected
            assert len({t["name"] for t in tags}) == expected
            assert all(t["state"] == "active" for t in tags)
            fr0 = st["frames_received"]
            time.sleep(1)
            assert s.get(f"{API}/sink", timeout=10).json()["frames_received"] > fr0

            vals_before = {t["name"]: t["value"] for t in s.get(f"{API}/sink/tags", timeout=10).json()}
            t0 = time.time()
            s.post(f"{API}/runtime/stop", timeout=10)
            st = _wait(lambda: (lambda d: d if d["dormant_count"] == d["tag_count"] else None)(s.get(f"{API}/sink", timeout=10).json()), timeout=5, step=0.2)
            print(f"cycle {i} ({fmt}): dormant in {time.time()-t0:.2f}s")
            assert st, f"cycle {i}: tags not all dormant"
            tags = s.get(f"{API}/sink/tags", timeout=10).json()
            assert all(t["state"] == "dormant" for t in tags)
            for t in tags:
                assert t["value"] is not None
            # values preserved (approximately last seen)
            assert set(vals_before) == {t["name"] for t in tags}
            if i == 0:
                events["revived"].clear()
            time.sleep(0.5)
        print("revived seen:", events["revived"], "new:", events["new"])
        assert len(events["revived"]) == expected
        assert len(events["new"]) == expected  # only first cycle creates
    finally:
        sio.disconnect()


# --- external OPC UA client sees sink nodes, dormant status after stop
def test_opcua_client_status_codes(s):
    from asyncua import Client, ua

    async def read_all():
        async with Client(SINK_EP) as c:
            idx = await c.get_namespace_index("http://emergent.sink/opcua")
            folder = await c.nodes.objects.get_child([f"{idx}:Received"])
            kids = await folder.get_children()
            out = {}
            for k in kids:
                dv = await k.read_attribute(13, None, False)
                out[(await k.read_browse_name()).Name] = dv.StatusCode_.value if hasattr(dv, "StatusCode_") else dv.StatusCode.value
            return out

    sink_tags = s.get(f"{API}/sink/tags", timeout=10).json()
    dormant = asyncio.run(read_all())
    assert len(dormant) == len(sink_tags)
    assert all(v == ua.StatusCodes.UncertainLastUsableValue for v in dormant.values()), dormant

    s.post(f"{API}/runtime/start", json={"format": "json", "serial_port": TX, "baudrate": 115200}, timeout=10)
    _wait(lambda: s.get(f"{API}/sink", timeout=10).json()["dormant_count"] == 0, timeout=15)
    active = asyncio.run(read_all())
    s.post(f"{API}/runtime/stop", timeout=10)
    assert len(active) == len(dormant)
    assert all(v == ua.StatusCodes.Good for v in active.values()), active
