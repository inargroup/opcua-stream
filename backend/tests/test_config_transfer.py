# Config download/upload (export/import) + iteration_5 regression tests (estimate baud validation)
import copy
import json
import os
import time
import uuid

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"
ORIG_PATH = "/tmp/orig_config.json"


def export():
    r = requests.get(f"{API}/config/export", timeout=30)
    assert r.status_code == 200, r.text
    return r.json()


def imp(cfg):
    return requests.post(f"{API}/config/import", json=cfg, timeout=60)


def norm(cfg):
    return (
        sorted(cfg["servers"], key=lambda s: s["id"]),
        sorted(cfg["tags"], key=lambda t: t["id"]),
        cfg["settings"],
    )


@pytest.fixture(scope="module", autouse=True)
def original():
    cfg = export()
    if not os.path.exists(ORIG_PATH):
        json.dump(cfg, open(ORIG_PATH, "w"))
    orig = json.load(open(ORIG_PATH))
    yield orig
    # restore original configuration
    r = imp(orig)
    assert r.status_code == 200, r.text


# --- Export shape ---
class TestExport:
    def test_export_shape(self):
        c = export()
        assert c["app"] == "opc-stream" and c["version"] == 1 and isinstance(c["exported_at"], str)
        assert "password" not in json.dumps(c).lower()
        for s in c["servers"]:
            assert set(s) == {"id", "name", "endpoint", "security_policy", "username"}
        for t in c["tags"]:
            assert set(t) == {"id", "server_id", "node_id", "name", "data_type", "unit", "sampling_interval"}
        assert set(c["settings"]) == {"format", "silence_timeout", "sender_port", "sender_baudrate", "receiver_port", "receiver_baudrate"}


# --- Import round-trip and replace semantics ---
class TestImport:
    def test_round_trip(self, original):
        r = imp(original)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["servers"] == len(original["servers"]) and d["tags"] == len(original["tags"])
        assert d["connected"] >= 1 and d["password_needed"] == []
        assert norm(export()) == norm(original)

    def test_modified_replace(self, original):
        cfg = copy.deepcopy(original)
        cfg["tags"] = cfg["tags"][:3]
        cfg["tags"][0]["sampling_interval"] = 777
        cfg["settings"]["sender_baudrate"] = 57600
        cfg["settings"]["format"] = "msgpack"
        cfg["settings"]["silence_timeout"] = 12.5
        r = imp(cfg)
        assert r.status_code == 200, r.text
        assert r.json()["tags"] == 3
        e = export()
        assert norm(e) == norm(cfg)
        tags = requests.get(f"{API}/tags", timeout=30).json()
        assert len(tags) == 3
        assert any(t["sampling_interval"] == 777 for t in tags)
        assert requests.get(f"{API}/runtime", timeout=30).json()["format"] == "msgpack"
        assert requests.get(f"{API}/sink", timeout=30).json()["silence_timeout"] == 12.5
        st = requests.get(f"{API}/serial/ports", timeout=30).json()["settings"]
        assert st["sender_baudrate"] == 57600

    def test_password_preservation_and_needed(self, original):
        # create a server with username+password via API
        r = requests.post(f"{API}/servers", json={"name": "TEST_auth", "endpoint": "opc.tcp://127.0.0.1:4999", "security_policy": "None", "username": "bob", "password": "secret"}, timeout=60)
        assert r.status_code in (200, 201), r.text
        cfg = export()
        srv = next(s for s in cfg["servers"] if s["name"] == "TEST_auth")
        new_srv = {"id": str(uuid.uuid4()), "name": "TEST_new_user", "endpoint": "opc.tcp://127.0.0.1:4998", "security_policy": "None", "username": "alice"}
        cfg["servers"].append(new_srv)
        r = imp(cfg)
        assert r.status_code == 200, r.text
        assert r.json()["password_needed"] == ["TEST_new_user"]
        # changed username -> password lost
        cfg2 = export()
        for s in cfg2["servers"]:
            if s["id"] == srv["id"]:
                s["username"] = "bob2"
        r = imp(cfg2)
        assert set(r.json()["password_needed"]) == {"TEST_auth", "TEST_new_user"}


# --- Import validation ---
class TestImportValidation:
    @pytest.mark.parametrize("mut,code", [
        (lambda c: c.update(app="other"), 400),
        (lambda c: c.update(version=2), 400),
        (lambda c: c["tags"][0].update(server_id="nope"), 400),
        (lambda c: c["tags"].append(dict(c["tags"][0], id="x")), 400),
        (lambda c: c["settings"].update(sender_baudrate=1234), 400),
        (lambda c: c["settings"].update(receiver_baudrate=0), 400),
        (lambda c: c["settings"].update(format="xml"), 400),
        (lambda c: c["servers"].append(dict(c["servers"][0])), 400),
        (lambda c: c.pop("servers"), 422),
        (lambda c: c["tags"][0].update(sampling_interval=5), 422),
        (lambda c: c["settings"].update(silence_timeout=5000), 422),
    ])
    def test_invalid(self, original, mut, code):
        before = norm(export())
        c = copy.deepcopy(original)
        mut(c)
        r = imp(c)
        assert r.status_code == code, r.text
        assert norm(export())[:2] == before[:2]  # unchanged

    def test_malformed_body(self):
        r = requests.post(f"{API}/config/import", data="not json", headers={"Content-Type": "application/json"}, timeout=30)
        assert r.status_code == 422

    def test_import_while_receiver_running_409(self, original):
        r = requests.post(f"{API}/sink/start", json={"serial_port": "/tmp/ttyV1", "baudrate": 115200, "silence_timeout": 5}, timeout=30)
        assert r.status_code == 200, r.text
        try:
            r = imp(original)
            assert r.status_code == 409
        finally:
            requests.post(f"{API}/sink/stop", timeout=30)

    def test_import_while_runtime_active_409(self, original):
        imp(original)
        time.sleep(2)
        r = requests.post(f"{API}/runtime/start", json={"format": "json", "serial_port": "/tmp/ttyV0", "baudrate": 115200}, timeout=30)
        assert r.status_code == 200, r.text
        try:
            r = imp(original)
            assert r.status_code == 409
        finally:
            requests.post(f"{API}/runtime/stop", timeout=30)


# --- Regression iteration_5: estimate baud validation ---
class TestEstimate:
    @pytest.mark.parametrize("b", [0, 1234])
    def test_bad_baud(self, b):
        r = requests.get(f"{API}/runtime/estimate", params={"format": "json", "baudrate": b}, timeout=30)
        assert r.status_code == 400

    def test_good_baud(self):
        r = requests.get(f"{API}/runtime/estimate", params={"format": "json", "baudrate": 115200}, timeout=30)
        assert r.status_code == 200 and r.json()["status"] == "ok"
