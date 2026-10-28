import os, time, requests
from dotenv import load_dotenv
load_dotenv("/app/frontend/.env")
API = os.environ["REACT_APP_BACKEND_URL"].rstrip("/") + "/api"
s = requests.Session()
s.post(f"{API}/runtime/stop"); s.post(f"{API}/sink/stop")
for fmt in ("json", "msgpack"):
    s.post(f"{API}/runtime/start", json={"format": fmt, "serial_port": "/tmp/ttyV0", "baudrate": 115200}); time.sleep(8); s.post(f"{API}/runtime/stop"); time.sleep(1)
s.post(f"{API}/sink/start", json={"serial_port": "/tmp/ttyV1", "baudrate": 115200, "silence_timeout": 2})
for i in range(8):
    time.sleep(1); d = s.get(f"{API}/sink").json()
    print(i, [a["code"] for a in d["alarms"]], "frames", d["frames_received"], "tags", d["tag_count"], "crc", d["crc_errors"], "bytes", d["bytes_received"])
s.post(f"{API}/sink/stop")
