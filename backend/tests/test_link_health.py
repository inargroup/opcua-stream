"""Link Health Alarm + Speed Advisor tests (socat pair /tmp/ttyV0 <-> /tmp/ttyV1)."""
import os
import time

import pytest
import requests
import serial
from dotenv import load_dotenv

load_dotenv("/app/frontend/.env")
API = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"
TX, RX = "/tmp/ttyV0", "/tmp/ttyV1"
CORRUPT = b"\xA5\x5A\x00\x00\x00\x00\x03abc\x00\x00\x00\x00"


@pytest.fixture(scope="module")
def s():
    sess = requests.Session()
    sess.post(f"{API}/runtime/stop", timeout=10)
    sess.post(f"{API}/sink/stop", timeout=10)
    yield sess
    sess.post(f"{API}/runtime/stop", timeout=10)


def codes(s):
    return [a["code"] for a in s.get(f"{API}/sink", timeout=10).json()["alarms"]]


def wait(pred, timeout=10, step=0.3):
    end = time.time() + timeout
    while time.time() < end:
        v = pred()
        if v:
            return v
        time.sleep(step)
    return pred()


# --- Speed advisor estimate
class TestEstimate:
    def test_9600_json_overloaded(self, s):
        d = s.get(f"{API}/runtime/estimate", params={"format": "json", "baudrate": 9600}, timeout=15).json()
        print(d)
        assert d["status"] == "overloaded"
        assert d["capacity_bytes_per_s"] == 960.0
        assert d["load_percent"] > 100
        assert d["suggested_baudrate"] and d["suggested_baudrate"] > 9600
        assert d["est_bytes_per_s"] / (d["suggested_baudrate"] / 10) <= 0.7
        assert d["tag_count"] == 9

    def test_115200_ok(self, s):
        for fmt in ("json", "msgpack"):
            d = s.get(f"{API}/runtime/estimate", params={"format": fmt, "baudrate": 115200}, timeout=15).json()
            print(d)
            assert d["status"] == "ok" and d["load_percent"] <= 70
            assert d["suggested_baudrate"] is None
            assert d["capacity_bytes_per_s"] == 11520.0

    def test_msgpack_smaller(self, s):
        j = s.get(f"{API}/runtime/estimate", params={"format": "json", "baudrate": 9600}, timeout=15).json()
        m = s.get(f"{API}/runtime/estimate", params={"format": "msgpack", "baudrate": 9600}, timeout=15).json()
        assert m["est_bytes_per_s"] < j["est_bytes_per_s"]

    def test_bad_format(self, s):
        assert s.get(f"{API}/runtime/estimate", params={"format": "xml", "baudrate": 9600}, timeout=10).status_code == 400

    def test_bad_baud(self, s):
        r = s.get(f"{API}/runtime/estimate", params={"format": "json", "baudrate": 0}, timeout=10)
        print("baud=0:", r.status_code, r.text[:200])
        r = s.get(f"{API}/runtime/estimate", params={"format": "json", "baudrate": 1234}, timeout=10)
        print("baud=1234:", r.status_code, r.text[:200])

    def test_estimate_vs_measured(self, s):
        for fmt in ("json", "msgpack"):
            est = s.get(f"{API}/runtime/estimate", params={"format": fmt, "baudrate": 115200}, timeout=15).json()
            r = s.post(f"{API}/runtime/start", json={"format": fmt, "serial_port": TX, "baudrate": 115200}, timeout=10)
            assert r.status_code == 200, r.text
            time.sleep(4)
            samples = []
            for _ in range(8):
                samples.append(s.get(f"{API}/runtime", timeout=10).json()["bps"])
                time.sleep(0.5)
            s.post(f"{API}/runtime/stop", timeout=10)
            measured = sum(samples) / len(samples)
            # measured bps excludes 11B frame overhead; estimate includes it
            ratio = est["est_bytes_per_s"] / measured if measured else 0
            print(f"{fmt}: est={est['est_bytes_per_s']} measured(payload)={measured:.1f} ratio={ratio:.2f}")
            assert 0.6 <= ratio <= 1.4
            time.sleep(1)


# --- Sink config / silence_timeout validation
class TestSinkConfig:
    def test_start_validation(self, s):
        for bad in (0, 0.4, 4000):
            r = s.post(f"{API}/sink/start", json={"serial_port": RX, "baudrate": 115200, "silence_timeout": bad}, timeout=10)
            assert r.status_code == 422, (bad, r.text)
        assert s.get(f"{API}/sink", timeout=10).json()["running"] is False

    def test_start_default_and_config(self, s):
        # drain stale bytes buffered by socat from earlier sender sessions (see repro_stale_frames_on_sink_start.py)
        s.post(f"{API}/sink/start", json={"serial_port": RX, "baudrate": 115200}, timeout=10)
        time.sleep(1)
        s.post(f"{API}/sink/stop", timeout=10)
        r = s.post(f"{API}/sink/start", json={"serial_port": RX, "baudrate": 115200}, timeout=10)
        assert r.status_code == 200, r.text
        assert r.json()["silence_timeout"] == 5.0
        assert r.json()["alarms"] == []
        r = s.post(f"{API}/sink/config", json={"silence_timeout": 2}, timeout=10)
        assert r.status_code == 200 and r.json()["silence_timeout"] == 2.0
        assert s.post(f"{API}/sink/config", json={"silence_timeout": 0}, timeout=10).status_code == 422
        assert s.get(f"{API}/sink", timeout=10).json()["silence_timeout"] == 2.0


# --- Alarms (run sequentially, sink running with silence_timeout=2)
class TestAlarms:
    def test_line_silent_appears(self, s):
        assert wait(lambda: "line_silent" in codes(s), timeout=6)
        a = [x for x in s.get(f"{API}/sink", timeout=10).json()["alarms"] if x["code"] == "line_silent"][0]
        assert a["severity"] == "critical" and a["since"] > 2

    def test_line_silent_clears_on_data_and_clean_stop_no_alarm(self, s):
        r = s.post(f"{API}/runtime/start", json={"format": "json", "serial_port": TX, "baudrate": 115200}, timeout=10)
        assert r.status_code == 200
        assert wait(lambda: "line_silent" not in codes(s), timeout=4)
        time.sleep(3)
        sk = s.get(f"{API}/sink", timeout=10).json()
        assert sk["tag_count"] == 9 and sk["alarms"] == [], sk["alarms"]
        s.post(f"{API}/runtime/stop", timeout=10)
        time.sleep(5)  # > silence_timeout
        sk = s.get(f"{API}/sink", timeout=10).json()
        assert "line_silent" not in [a["code"] for a in sk["alarms"]], sk["alarms"]
        assert sk["dormant_count"] == 9

    def test_crc_alarm_appears_and_clears(self, s):
        # raise silence timeout so only CRC alarm is in play; write raw garbage on the TX side
        s.post(f"{API}/sink/config", json={"silence_timeout": 60}, timeout=10)
        before = s.get(f"{API}/sink", timeout=10).json()["crc_errors"]
        with serial.Serial(TX, 115200) as p:
            p.write(CORRUPT)
            p.flush()
        t0 = time.time()
        assert wait(lambda: "crc_errors" in codes(s), timeout=4)
        sk = s.get(f"{API}/sink", timeout=10).json()
        a = [x for x in sk["alarms"] if x["code"] == "crc_errors"][0]
        assert a["severity"] == "warning" and a["count"] >= 1
        assert sk["crc_errors"] > before
        # corrupt frame bytes reset last_rx? control: silent alarm absent since 60s limit
        assert wait(lambda: "crc_errors" not in codes(s), timeout=15, step=0.5)
        took = time.time() - t0
        print(f"crc alarm cleared after {took:.1f}s")
        assert 9 <= took <= 13

    def test_corrupt_bytes_after_clean_stop_line_silent(self, s):
        """After a clean stop, garbage bytes do not reset clean_stop (only decoded frames do)."""
        s.post(f"{API}/sink/config", json={"silence_timeout": 1}, timeout=10)
        time.sleep(2)
        print("alarms after clean stop + garbage:", codes(s))

    def test_regression_restart_revives(self, s):
        s.post(f"{API}/sink/config", json={"silence_timeout": 5}, timeout=10)
        for fmt in ("msgpack", "json"):
            assert s.post(f"{API}/runtime/start", json={"format": fmt, "serial_port": TX, "baudrate": 115200}, timeout=10).status_code == 200
            assert wait(lambda: s.get(f"{API}/sink", timeout=10).json()["dormant_count"] == 0, timeout=6)
            assert s.get(f"{API}/sink", timeout=10).json()["tag_count"] == 9
            s.post(f"{API}/runtime/stop", timeout=10)
            assert wait(lambda: s.get(f"{API}/sink", timeout=10).json()["dormant_count"] == 9, timeout=6)
        assert s.get(f"{API}/sink", timeout=10).json()["tag_count"] == 9
