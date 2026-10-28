import asyncio
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import msgpack
import socketio
from asyncua import Client, ua
from dotenv import load_dotenv
from fastapi import APIRouter, FastAPI, HTTPException
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field
from starlette.middleware.cors import CORSMiddleware

from opcua_demo import DemoOPCUAServer
from opcua_sink import SinkOPCUAServer
from serial_link import BAUD_RATES, SerialReceiver, SerialSender, list_serial_ports

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("opcua_app")
for noisy in ("asyncua", "asyncua.server.uaprocessor", "asyncua.server.internal_session", "asyncua.server.address_space"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

mongo_url = os.environ["MONGO_URL"]
mongo_client = AsyncIOMotorClient(mongo_url)
db = mongo_client[os.environ["DB_NAME"]]

DEMO_ENDPOINT = "opc.tcp://127.0.0.1:4840/emergent/server/"
DEMO_SERVER_ID = "demo-server"

# ---------------------------------------------------------------------------
# Socket.IO + FastAPI
# ---------------------------------------------------------------------------
sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*", max_http_buffer_size=10_000_000)
fastapi_app = FastAPI(title="OPC UA Multi-Server Client")
api_router = APIRouter(prefix="/api")

# ---------------------------------------------------------------------------
# In-memory runtime state
# ---------------------------------------------------------------------------
demo_server = DemoOPCUAServer(DEMO_ENDPOINT)
connections: dict = {}  # server_id -> {"client", "connected", "error"}
runtime = {
    "active": False,
    "format": "json",  # "json" | "msgpack"
    "task": None,
    "seq": 0,
    "frames_total": 0,
    "bytes_total": 0,
    "started_at": None,
    "_win_start": 0.0,
    "_win_frames": 0,
    "_win_bytes": 0,
    "fps": 0.0,
    "bps": 0.0,
    "active_tag_count": 0,
    "serial_port": None,
    "baudrate": None,
    "link": None,
    "last_values": {},
}
DORMANT_AFTER = 3.0  # min seconds of silence (or 3x the tag's sampling interval) before a tag is flagged dormant

# ---- Sink / receiver state ----
sink_server = SinkOPCUAServer()
sink_state = {
    "running": False,
    "serial_port": None,
    "baudrate": None,
    "link": None,
    "consumer": None,
    "monitor": None,
    "frames_received": 0,
    "bytes_received": 0,
    "started_at": None,
    "_win_start": 0.0,
    "_win_frames": 0,
    "_win_bytes": 0,
    "fps": 0.0,
    "bps": 0.0,
    "last_seq": 0,
    "silence_timeout": 5.0,
    "last_rx": 0.0,
    "clean_stop": False,
    "_crc_seen": 0,
    "_crc_events": None,
}
CRC_WINDOW = 10.0
sink_data = {"tags": {}}  # name -> {name,value,quality,state,sample_count,first_seen,last_update}


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class ServerCreate(BaseModel):
    name: str
    endpoint: str
    security_policy: str = "None"
    username: Optional[str] = None
    password: Optional[str] = None


class ServerUpdate(BaseModel):
    name: Optional[str] = None
    endpoint: Optional[str] = None
    security_policy: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None


class TagCreate(BaseModel):
    server_id: str
    node_id: str
    name: str
    data_type: str = "Unknown"
    unit: Optional[str] = None
    sampling_interval: int = 200  # ms


class TagUpdate(BaseModel):
    name: Optional[str] = None
    sampling_interval: Optional[int] = None


class RuntimeStart(BaseModel):
    format: str = "json"
    serial_port: Optional[str] = None
    baudrate: int = 115200


class FormatSet(BaseModel):
    format: str


class SinkStart(BaseModel):
    serial_port: str
    baudrate: int = 115200
    silence_timeout: float = Field(5.0, ge=0.5, le=3600)


class SinkConfig(BaseModel):
    silence_timeout: float = Field(ge=0.5, le=3600)


async def _save_serial_setting(role: str, port: Optional[str], baudrate: int):
    await db.app_settings.update_one(
        {"id": "serial"}, {"$set": {f"{role}_port": port, f"{role}_baudrate": baudrate}}, upsert=True
    )


def now_iso():
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# OPC UA client helpers
# ---------------------------------------------------------------------------
async def _connect_server(cfg: dict):
    """Open a genuine OPC UA session for a stored server config."""
    server_id = cfg["id"]
    existing = connections.get(server_id)
    if existing and existing.get("connected"):
        return {"connected": True}

    client = Client(url=cfg["endpoint"])
    if cfg.get("username"):
        client.set_user(cfg["username"])
    if cfg.get("password"):
        client.set_password(cfg["password"])
    try:
        await asyncio.wait_for(client.connect(), timeout=8)
        connections[server_id] = {"client": client, "connected": True, "error": None}
        logger.info(f"Connected to {cfg['endpoint']}")
        return {"connected": True}
    except Exception as e:  # noqa
        try:
            await client.disconnect()
        except Exception:
            pass
        connections[server_id] = {"client": None, "connected": False, "error": str(e)}
        logger.warning(f"Connect failed {cfg['endpoint']}: {e}")
        return {"connected": False, "error": str(e)}


async def _disconnect_server(server_id: str):
    conn = connections.get(server_id)
    if conn and conn.get("client"):
        try:
            await conn["client"].disconnect()
        except Exception:
            pass
    connections[server_id] = {"client": None, "connected": False, "error": None}


def _status(server_id: str):
    conn = connections.get(server_id)
    if not conn:
        return {"connected": False, "error": None}
    return {"connected": conn.get("connected", False), "error": conn.get("error")}


async def _browse_node(client: Client, node_id: Optional[str]):
    node = client.get_node(node_id) if node_id else client.nodes.objects
    children = await node.get_children()
    out = []
    for child in children:
        try:
            nclass = await child.read_node_class()
            bname = await child.read_browse_name()
            nid = child.nodeid.to_string()
            entry = {
                "node_id": nid,
                "name": bname.Name,
                "node_class": nclass.name,
                "is_variable": nclass == ua.NodeClass.Variable,
            }
            if entry["is_variable"]:
                try:
                    val = await child.read_value()
                    entry["value"] = _to_jsonable(val)
                    vt = await child.read_data_type_as_variant_type()
                    entry["data_type"] = vt.name
                except Exception:
                    entry["value"] = None
                    entry["data_type"] = "Unknown"
            else:
                grandkids = await child.get_children()
                entry["has_children"] = len(grandkids) > 0
            out.append(entry)
        except Exception as e:  # noqa
            logger.debug(f"browse child error: {e}")
    return out


def _to_jsonable(val):
    if isinstance(val, (int, float, bool, str)) or val is None:
        return val
    return str(val)


# ---------------------------------------------------------------------------
# Server endpoints
# ---------------------------------------------------------------------------
@api_router.get("/")
async def root():
    return {"message": "OPC UA Multi-Server Client API", "demo_endpoint": DEMO_ENDPOINT}


@api_router.get("/servers")
async def list_servers():
    servers = await db.opcua_servers.find({}, {"_id": 0}).to_list(1000)
    for s in servers:
        s["status"] = _status(s["id"])
        s["tag_count"] = await db.opcua_tags.count_documents({"server_id": s["id"]})
    return servers


@api_router.post("/servers")
async def create_server(body: ServerCreate):
    doc = body.model_dump()
    doc["id"] = str(uuid.uuid4())
    doc["created_at"] = now_iso()
    await db.opcua_servers.insert_one(doc.copy())
    doc.pop("_id", None)
    doc["status"] = _status(doc["id"])
    doc["tag_count"] = 0
    return doc


@api_router.put("/servers/{server_id}")
async def update_server(server_id: str, body: ServerUpdate):
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(400, "No updates provided")
    res = await db.opcua_servers.update_one({"id": server_id}, {"$set": updates})
    if res.matched_count == 0:
        raise HTTPException(404, "Server not found")
    doc = await db.opcua_servers.find_one({"id": server_id}, {"_id": 0})
    doc["status"] = _status(server_id)
    return doc


@api_router.delete("/servers/{server_id}")
async def delete_server(server_id: str):
    await _disconnect_server(server_id)
    await db.opcua_tags.delete_many({"server_id": server_id})
    await db.opcua_servers.delete_one({"id": server_id})
    connections.pop(server_id, None)
    return {"deleted": True}


@api_router.post("/servers/{server_id}/connect")
async def connect_server(server_id: str):
    cfg = await db.opcua_servers.find_one({"id": server_id}, {"_id": 0})
    if not cfg:
        raise HTTPException(404, "Server not found")
    result = await _connect_server(cfg)
    if not result.get("connected"):
        raise HTTPException(502, result.get("error", "Connection failed"))
    return {"server_id": server_id, "status": _status(server_id)}


@api_router.post("/servers/{server_id}/disconnect")
async def disconnect_server(server_id: str):
    await _disconnect_server(server_id)
    return {"server_id": server_id, "status": _status(server_id)}


@api_router.get("/servers/{server_id}/browse")
async def browse_server(server_id: str, node_id: Optional[str] = None):
    conn = connections.get(server_id)
    if not conn or not conn.get("connected"):
        raise HTTPException(400, "Server not connected")
    try:
        nodes = await _browse_node(conn["client"], node_id)
        return {"server_id": server_id, "parent": node_id, "nodes": nodes}
    except Exception as e:  # noqa
        raise HTTPException(502, f"Browse failed: {e}")


# ---------------------------------------------------------------------------
# Tag endpoints
# ---------------------------------------------------------------------------
@api_router.get("/tags")
async def list_tags(server_id: Optional[str] = None):
    query = {"server_id": server_id} if server_id else {}
    return await db.opcua_tags.find(query, {"_id": 0}).to_list(2000)


@api_router.post("/tags")
async def create_tag(body: TagCreate):
    existing = await db.opcua_tags.find_one({"server_id": body.server_id, "node_id": body.node_id})
    if existing:
        raise HTTPException(409, "Tag already exists for this server")
    doc = body.model_dump()
    doc["id"] = str(uuid.uuid4())
    doc["created_at"] = now_iso()
    await db.opcua_tags.insert_one(doc.copy())
    doc.pop("_id", None)
    return doc


@api_router.put("/tags/{tag_id}")
async def update_tag(tag_id: str, body: TagUpdate):
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(400, "No updates provided")
    res = await db.opcua_tags.update_one({"id": tag_id}, {"$set": updates})
    if res.matched_count == 0:
        raise HTTPException(404, "Tag not found")
    return await db.opcua_tags.find_one({"id": tag_id}, {"_id": 0})


@api_router.delete("/tags/{tag_id}")
async def delete_tag(tag_id: str):
    await db.opcua_tags.delete_one({"id": tag_id})
    return {"deleted": True}


# ---------------------------------------------------------------------------
# Runtime / transmission
# ---------------------------------------------------------------------------
def _runtime_status():
    uptime = (time.time() - runtime["started_at"]) if runtime["started_at"] else 0
    link = runtime["link"]
    return {
        "active": runtime["active"],
        "format": runtime["format"],
        "frames_total": runtime["frames_total"],
        "bytes_total": runtime["bytes_total"],
        "fps": round(runtime["fps"], 1),
        "bps": round(runtime["bps"], 1),
        "uptime": round(uptime, 1),
        "active_tag_count": runtime["active_tag_count"],
        "serial_port": runtime["serial_port"],
        "baudrate": runtime["baudrate"],
        "serial_connected": bool(link and link.connected),
        "serial_error": link.error if link else None,
        "dropped_frames": link.dropped if link else 0,
    }


@api_router.get("/runtime")
async def get_runtime():
    return _runtime_status()


@api_router.post("/runtime/start")
async def start_runtime(body: RuntimeStart):
    if runtime["active"]:
        return _runtime_status()
    if body.format not in ("json", "msgpack"):
        raise HTTPException(400, "Invalid format")
    if body.baudrate not in BAUD_RATES:
        raise HTTPException(400, "Unsupported baud rate")
    link = None
    if body.serial_port:
        link = SerialSender(body.serial_port, body.baudrate)
        try:
            await asyncio.to_thread(link.start)
        except Exception as e:  # noqa
            raise HTTPException(409, f"Could not open serial port {body.serial_port}: {e}")
    await _save_serial_setting("sender", body.serial_port, body.baudrate)
    runtime["link"] = link
    runtime["serial_port"] = body.serial_port
    runtime["baudrate"] = body.baudrate
    runtime["format"] = body.format
    runtime["active"] = True
    runtime["seq"] = 0
    runtime["frames_total"] = 0
    runtime["bytes_total"] = 0
    runtime["started_at"] = time.time()
    runtime["_win_start"] = time.time()
    runtime["_win_frames"] = 0
    runtime["_win_bytes"] = 0
    runtime["task"] = asyncio.create_task(_transmission_loop())
    logger.info(f"Runtime started ({body.format})")
    return _runtime_status()


@api_router.post("/runtime/stop")
async def stop_runtime():
    runtime["active"] = False
    if runtime["task"]:
        runtime["task"].cancel()
        runtime["task"] = None
    link = runtime["link"]
    if link:
        link.send(json.dumps({"ctl": "stop", "ts": now_iso()}).encode(), "control")
        await asyncio.to_thread(link.flush_and_close)
        runtime["link"] = None
    runtime["started_at"] = None
    runtime["fps"] = 0.0
    runtime["bps"] = 0.0
    logger.info("Runtime stopped")
    return _runtime_status()


@api_router.post("/runtime/format")
async def set_format(body: FormatSet):
    if body.format not in ("json", "msgpack"):
        raise HTTPException(400, "Invalid format")
    runtime["format"] = body.format
    return _runtime_status()


FRAME_OVERHEAD = 11  # SYNC + fmt + len + CRC32
TICK_S = 0.05


@api_router.get("/runtime/estimate")
async def estimate_link(format: str = "json", baudrate: int = 115200):
    """Simulate 10s of the transmission scheduler to estimate serial load for the configured tags."""
    if format not in ("json", "msgpack"):
        raise HTTPException(400, "Invalid format")
    if baudrate not in BAUD_RATES:
        raise HTTPException(400, "Unsupported baud rate")
    tags = await db.opcua_tags.find({}, {"_id": 0}).to_list(2000)
    last = runtime["last_values"]
    ticks = int(10 / TICK_S)
    nexts = {t["id"]: 0 for t in tags}
    total = frames = 0
    for k in range(ticks):
        now = k * TICK_S
        due = [t for t in tags if now + 1e-9 >= nexts[t["id"]]]
        if not due:
            continue
        for t in due:
            step = max(round(max(t.get("sampling_interval", 200), 20) / 1000 / TICK_S), 1) * TICK_S
            nexts[t["id"]] = now + step
        core = {
            "seq": 100000 + k,
            "ts": now_iso(),
            "samples": [{"n": t["name"], "v": last.get(t["name"], 1234.5678), "q": 192, "i": t.get("sampling_interval", 200)} for t in due],
        }
        packed = json.dumps(core, default=str).encode() if format == "json" else msgpack.packb(core, default=str, use_bin_type=True)
        total += len(packed) + FRAME_OVERHEAD
        frames += 1
    bps = total / 10
    capacity = lambda b: b / 10  # 8N1: 10 bits per byte
    load = bps / capacity(baudrate) * 100 if baudrate else 0
    suggested = next((b for b in BAUD_RATES if bps / capacity(b) <= 0.7), None)
    status = "ok" if load <= 70 else "tight" if load <= 100 else "overloaded"
    return {
        "format": format,
        "baudrate": baudrate,
        "tag_count": len(tags),
        "frames_per_s": round(frames / 10, 1),
        "est_bytes_per_s": round(bps, 1),
        "capacity_bytes_per_s": round(capacity(baudrate), 1),
        "load_percent": round(load, 1),
        "status": status,
        "suggested_baudrate": suggested if status != "ok" else None,
    }


async def _read_tag_value(tag: dict):
    conn = connections.get(tag["server_id"])
    if not conn or not conn.get("connected"):
        return None, 0
    try:
        node = conn["client"].get_node(tag["node_id"])
        val = await node.read_value()
        return _to_jsonable(val), 192  # 192 ~ Good quality
    except Exception:
        return None, 0


async def _transmission_loop():
    base_tick = 0.05  # 50ms -> up to 20 Hz
    last_stats = time.time()
    last_reload = time.time()
    tags = await db.opcua_tags.find({}, {"_id": 0}).to_list(2000)
    for t in tags:
        t["_last"] = 0.0
    runtime["active_tag_count"] = len(tags)

    while runtime["active"]:
        loop_start = time.time()

        # Hot-reload tag list so newly added tags start streaming without a restart
        if loop_start - last_reload >= 2.0:
            fresh = await db.opcua_tags.find({}, {"_id": 0}).to_list(2000)
            prev_last = {t["id"]: t["_last"] for t in tags}
            for t in fresh:
                t["_last"] = prev_last.get(t["id"], 0.0)
            tags = fresh
            runtime["active_tag_count"] = len(tags)
            last_reload = loop_start

        due_samples = []
        for tag in tags:
            interval_s = max(tag.get("sampling_interval", 200), 20) / 1000.0
            if loop_start - tag["_last"] >= interval_s:
                val, quality = await _read_tag_value(tag)
                tag["_last"] = loop_start
                if val is not None:
                    runtime["last_values"][tag["name"]] = val
                due_samples.append(
                    {
                        "tag_id": tag["id"],
                        "name": tag["name"],
                        "node_id": tag["node_id"],
                        "server_id": tag["server_id"],
                        "unit": tag.get("unit"),
                        "interval": tag.get("sampling_interval", 200),
                        "value": val,
                        "quality": quality,
                    }
                )

        if due_samples:
            runtime["seq"] += 1
            core = {
                "seq": runtime["seq"],
                "ts": now_iso(),
                "samples": [{"n": s["name"], "v": s["value"], "q": s["quality"], "i": s["interval"]} for s in due_samples],
            }
            fmt = runtime["format"]
            if fmt == "json":
                packed = json.dumps(core, default=str).encode("utf-8")
                preview = packed.decode("utf-8")[:400]
            else:
                packed = msgpack.packb(core, default=str, use_bin_type=True)
                preview = packed.hex()[:400]

            size = len(packed)
            runtime["frames_total"] += 1
            runtime["bytes_total"] += size
            runtime["_win_frames"] += 1
            runtime["_win_bytes"] += size

            if runtime["link"]:
                runtime["link"].send(packed, fmt)

            await sio.emit(
                "frame",
                {
                    "seq": runtime["seq"],
                    "ts": core["ts"],
                    "format": fmt,
                    "byte_size": size,
                    "tag_count": len(due_samples),
                    "samples": due_samples,
                    "preview": preview,
                },
            )

        # stats window ~ every 0.5s
        now = time.time()
        if now - last_stats >= 0.5:
            win = now - runtime["_win_start"]
            if win > 0:
                runtime["fps"] = runtime["_win_frames"] / win
                runtime["bps"] = runtime["_win_bytes"] / win
            runtime["_win_start"] = now
            runtime["_win_frames"] = 0
            runtime["_win_bytes"] = 0
            last_stats = now
            await sio.emit("stats", _runtime_status())

        elapsed = time.time() - loop_start
        await asyncio.sleep(max(0.0, base_tick - elapsed))


# ---------------------------------------------------------------------------
# Sink / Receiver — ingest serialized stream over a serial port and re-publish
# on a dynamic OPC UA server. Tags are keyed by name, so a Sender restart
# revives existing (dormant) tags instead of creating new ones.
# ---------------------------------------------------------------------------
def _sink_status():
    uptime = (time.time() - sink_state["started_at"]) if sink_state["started_at"] else 0
    link = sink_state["link"]
    tags = sink_data["tags"].values()
    return {
        "running": sink_state["running"],
        "serial_port": sink_state["serial_port"],
        "baudrate": sink_state["baudrate"],
        "serial_connected": bool(link and link.connected),
        "serial_error": link.error if link else None,
        "crc_errors": link.decoder.crc_errors if link else 0,
        "opcua_endpoint": sink_server.endpoint,
        "frames_received": sink_state["frames_received"],
        "bytes_received": sink_state["bytes_received"],
        "fps": round(sink_state["fps"], 1),
        "bps": round(sink_state["bps"], 1),
        "tag_count": len(sink_data["tags"]),
        "dormant_count": sum(1 for r in tags if r["state"] == "dormant"),
        "last_seq": sink_state["last_seq"],
        "uptime": round(uptime, 1),
        "silence_timeout": sink_state["silence_timeout"],
        "alarms": _sink_alarms(),
    }


def _sink_alarms():
    if not sink_state["running"]:
        return []
    now = time.time()
    link = sink_state["link"]
    alarms = []
    if link and link.error:
        alarms.append({"code": "link_lost", "severity": "critical", "message": f"Serial port {sink_state['serial_port']} unavailable: {link.error}"})
    silent_for = now - sink_state["last_rx"]
    if not sink_state["clean_stop"] and silent_for > sink_state["silence_timeout"]:
        alarms.append({"code": "line_silent", "severity": "critical", "message": f"No data on {sink_state['serial_port']} for {silent_for:.0f}s (limit {sink_state['silence_timeout']:g}s) — check cable, baud rate and Sender", "since": round(silent_for, 1)})
    events = sink_state["_crc_events"] or []
    recent = sum(n for t, n in events if now - t <= CRC_WINDOW)
    if recent:
        alarms.append({"code": "crc_errors", "severity": "warning", "message": f"{recent} checksum error(s) in the last {CRC_WINDOW:g}s — possible noise, loose wiring or baud mismatch", "count": recent})
    return alarms


async def _mark_dormant(names):
    for name in names:
        sink_data["tags"][name]["state"] = "dormant"
        await sink_server.set_dormant(name)
    if names:
        logger.info(f"Sink tags dormant: {names}")
        await sio.emit("sink_dormant", {"names": names})
        await sio.emit("sink_stats", _sink_status())


async def _process_received(core: dict, fmt: str, size: int):
    seq = core.get("seq")
    ts = core.get("ts")
    samples = core.get("samples", [])
    now = time.time()
    new_tags = []
    revived = []
    out_samples = []
    for s in samples:
        name = s.get("n")
        val = s.get("v")
        q = s.get("q")
        if name is None:
            continue
        await sink_server.upsert(name, val)
        rec = sink_data["tags"].get(name)
        if rec is None:
            rec = {"name": name, "value": val, "quality": q, "state": "active", "sample_count": 0, "first_seen": now_iso(), "last_update": None}
            sink_data["tags"][name] = rec
            new_tags.append(name)
        elif rec["state"] == "dormant":
            rec["state"] = "active"
            revived.append(name)
        rec["value"] = val
        rec["quality"] = q
        rec["sample_count"] += 1
        rec["last_update"] = ts
        rec["_interval"] = (s.get("i") or 0) / 1000.0
        rec["_rx"] = now
        out_samples.append({"name": name, "value": val, "quality": q, "is_new": name in new_tags})

    if revived:
        logger.info(f"Sink tags revived: {revived}")

    sink_state["frames_received"] += 1
    sink_state["bytes_received"] += size
    sink_state["_win_frames"] += 1
    sink_state["_win_bytes"] += size
    sink_state["last_seq"] = seq

    await sio.emit(
        "sink_frame",
        {"seq": seq, "ts": ts, "format": fmt, "byte_size": size, "tag_count": len(out_samples), "samples": out_samples, "new_tags": new_tags, "revived": revived},
    )


async def _sink_consumer(q: asyncio.Queue):
    while True:
        fmt, payload, size = await q.get()
        sink_state["last_rx"] = time.time()
        try:
            if fmt == "control":
                if json.loads(payload).get("ctl") == "stop" and sink_state["frames_received"]:
                    sink_state["clean_stop"] = True
                    await _mark_dormant([n for n, r in sink_data["tags"].items() if r["state"] == "active"])
                continue
            core = json.loads(payload) if fmt == "json" else msgpack.unpackb(payload, raw=False)
            sink_state["clean_stop"] = False
            await _process_received(core, fmt, size)
        except Exception as e:  # noqa
            logger.warning(f"serial frame decode failed: {e}")


async def _sink_monitor():
    while True:
        await asyncio.sleep(0.5)
        now = time.time()
        stale = [n for n, r in sink_data["tags"].items() if r["state"] == "active" and now - r.get("_rx", now) > max(DORMANT_AFTER, 3 * r.get("_interval", 0))]
        await _mark_dormant(stale)
        link = sink_state["link"]
        if link and link.decoder.crc_errors > sink_state["_crc_seen"]:
            sink_state["_crc_events"].append((now, link.decoder.crc_errors - sink_state["_crc_seen"]))
            sink_state["_crc_seen"] = link.decoder.crc_errors
        sink_state["_crc_events"] = [e for e in sink_state["_crc_events"] if now - e[0] <= CRC_WINDOW]
        win = now - sink_state["_win_start"]
        if win > 0:
            sink_state["fps"] = sink_state["_win_frames"] / win
            sink_state["bps"] = sink_state["_win_bytes"] / win
        sink_state["_win_start"] = now
        sink_state["_win_frames"] = 0
        sink_state["_win_bytes"] = 0
        await sio.emit("sink_stats", _sink_status())


def _public_tag(r: dict):
    return {k: v for k, v in r.items() if not k.startswith("_")}


@api_router.get("/serial/ports")
async def get_serial_ports():
    settings = await db.app_settings.find_one({"id": "serial"}, {"_id": 0, "id": 0}) or {}
    return {"ports": await asyncio.to_thread(list_serial_ports), "baud_rates": BAUD_RATES, "settings": settings}


@api_router.get("/sink")
async def get_sink():
    return _sink_status()


@api_router.get("/sink/tags")
async def get_sink_tags():
    return [_public_tag(r) for r in sorted(sink_data["tags"].values(), key=lambda r: r["first_seen"])]


@api_router.post("/sink/start")
async def start_sink(body: SinkStart):
    if sink_state["running"]:
        return _sink_status()
    if body.baudrate not in BAUD_RATES:
        raise HTTPException(400, "Unsupported baud rate")
    q: asyncio.Queue = asyncio.Queue(maxsize=0)
    link = SerialReceiver(body.serial_port, body.baudrate, asyncio.get_running_loop(), q)
    try:
        await asyncio.to_thread(link.start)
    except Exception as e:  # noqa
        raise HTTPException(409, f"Could not open serial port {body.serial_port}: {e}")
    await _save_serial_setting("receiver", body.serial_port, body.baudrate)
    await sink_server.start()
    await sink_server.reset()
    sink_data["tags"] = {}
    sink_state.update(
        running=True,
        serial_port=body.serial_port,
        baudrate=body.baudrate,
        link=link,
        consumer=asyncio.create_task(_sink_consumer(q)),
        monitor=asyncio.create_task(_sink_monitor()),
        frames_received=0,
        bytes_received=0,
        started_at=time.time(),
        _win_start=time.time(),
        _win_frames=0,
        _win_bytes=0,
        fps=0.0,
        bps=0.0,
        last_seq=0,
        silence_timeout=body.silence_timeout,
        last_rx=time.time(),
        clean_stop=False,
        _crc_seen=0,
        _crc_events=[],
    )
    logger.info(f"Sink listening on serial {body.serial_port} @ {body.baudrate}")
    await sio.emit("sink_stats", _sink_status())
    return _sink_status()


@api_router.post("/sink/config")
async def config_sink(body: SinkConfig):
    sink_state["silence_timeout"] = body.silence_timeout
    await sio.emit("sink_stats", _sink_status())
    return _sink_status()


@api_router.post("/sink/stop")
async def stop_sink():
    for key in ("consumer", "monitor"):
        if sink_state[key]:
            sink_state[key].cancel()
    if sink_state["link"]:
        await asyncio.to_thread(sink_state["link"].close)
    sink_state.update(running=False, link=None, consumer=None, monitor=None, started_at=None, fps=0.0, bps=0.0)
    await sio.emit("sink_stats", _sink_status())
    return _sink_status()


# ---------------------------------------------------------------------------
# Configuration download / upload (passwords are never exported)
# ---------------------------------------------------------------------------
CONFIG_APP = "opc-stream"
CONFIG_VERSION = 1
SETTING_KEYS = ("sender_port", "sender_baudrate", "receiver_port", "receiver_baudrate")


class ConfigServer(BaseModel):
    id: str
    name: str
    endpoint: str
    security_policy: str = "None"
    username: Optional[str] = None


class ConfigTag(BaseModel):
    id: str
    server_id: str
    node_id: str
    name: str
    data_type: str = "Unknown"
    unit: Optional[str] = None
    sampling_interval: int = Field(200, ge=20, le=3_600_000)


class ConfigSettings(BaseModel):
    format: str = "json"
    silence_timeout: float = Field(5.0, ge=0.5, le=3600)
    sender_port: Optional[str] = None
    sender_baudrate: int = 115200
    receiver_port: Optional[str] = None
    receiver_baudrate: int = 115200


class ConfigFile(BaseModel):
    app: str
    version: int
    servers: List[ConfigServer]
    tags: List[ConfigTag]
    settings: ConfigSettings = ConfigSettings()


@api_router.get("/config/export")
async def export_config():
    servers = await db.opcua_servers.find({}, {"_id": 0, "password": 0, "created_at": 0}).to_list(1000)
    tags = await db.opcua_tags.find({}, {"_id": 0, "created_at": 0}).to_list(5000)
    st = await db.app_settings.find_one({"id": "serial"}, {"_id": 0}) or {}
    settings = {k: st.get(k) for k in SETTING_KEYS if st.get(k) is not None}
    settings.update(format=runtime["format"], silence_timeout=sink_state["silence_timeout"])
    return {
        "app": CONFIG_APP,
        "version": CONFIG_VERSION,
        "exported_at": now_iso(),
        "servers": [ConfigServer(**s).model_dump() for s in servers],
        "tags": [ConfigTag(**t).model_dump() for t in tags],
        "settings": ConfigSettings(**settings).model_dump(),
    }


@api_router.post("/config/import")
async def import_config(body: ConfigFile):
    if body.app != CONFIG_APP or body.version > CONFIG_VERSION:
        raise HTTPException(400, "Not an OPC//STREAM configuration file (or a newer version)")
    if runtime["active"] or sink_state["running"]:
        raise HTTPException(409, "Stop the transmission and the receiver before uploading a configuration")
    s = body.settings
    if s.format not in ("json", "msgpack"):
        raise HTTPException(400, "Invalid format in settings")
    if s.sender_baudrate not in BAUD_RATES or s.receiver_baudrate not in BAUD_RATES:
        raise HTTPException(400, "Unsupported baud rate in settings")
    server_ids = [srv.id for srv in body.servers]
    if len(set(server_ids)) != len(server_ids):
        raise HTTPException(400, "Duplicate server ids in file")
    seen = set()
    for t in body.tags:
        if t.server_id not in server_ids:
            raise HTTPException(400, f"Tag '{t.name}' refers to an unknown server")
        if (t.server_id, t.node_id) in seen:
            raise HTTPException(400, f"Duplicate tag '{t.name}' for the same server")
        seen.add((t.server_id, t.node_id))

    # keep stored passwords for servers that survive the replace with the same endpoint + user
    old = {o["id"]: o for o in await db.opcua_servers.find({}, {"_id": 0}).to_list(1000)}
    for sid in list(connections.keys()):
        await _disconnect_server(sid)
    connections.clear()
    await db.opcua_tags.delete_many({})
    await db.opcua_servers.delete_many({})

    password_needed = []
    for srv in body.servers:
        doc = srv.model_dump()
        prev = old.get(srv.id)
        same = prev and prev.get("endpoint") == srv.endpoint and prev.get("username") == srv.username
        doc["password"] = prev.get("password") if same else None
        doc["created_at"] = now_iso()
        if srv.username and not doc["password"]:
            password_needed.append(srv.name)
        await db.opcua_servers.insert_one(doc)
    if body.tags:
        await db.opcua_tags.insert_many([{**t.model_dump(), "created_at": now_iso()} for t in body.tags])

    await db.app_settings.update_one(
        {"id": "serial"},
        {"$set": {**{k: getattr(s, k) for k in SETTING_KEYS}, "config_imported": True}},
        upsert=True,
    )
    runtime["format"] = s.format
    sink_state["silence_timeout"] = s.silence_timeout

    connected = 0
    for srv in await db.opcua_servers.find({}, {"_id": 0}).to_list(1000):
        if (await _connect_server(srv)).get("connected"):
            connected += 1
    logger.info(f"Configuration imported: {len(body.servers)} servers, {len(body.tags)} tags")
    return {
        "servers": len(body.servers),
        "tags": len(body.tags),
        "connected": connected,
        "password_needed": password_needed,
        "settings": s.model_dump(),
    }


# ---------------------------------------------------------------------------
# Socket.IO events
# ---------------------------------------------------------------------------
@sio.event
async def connect(sid, environ):
    logger.info(f"WS client connected: {sid}")
    await sio.emit("stats", _runtime_status(), to=sid)
    await sio.emit("sink_stats", _sink_status(), to=sid)


@sio.event
async def disconnect(sid):
    logger.info(f"WS client disconnected: {sid}")


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------
async def _seed_demo():
    settings = await db.app_settings.find_one({"id": "serial"}) or {}
    if settings.get("config_imported"):
        return
    existing = await db.opcua_servers.find_one({"id": DEMO_SERVER_ID})
    if not existing:
        await db.opcua_servers.insert_one(
            {
                "id": DEMO_SERVER_ID,
                "name": "Demo Plant (built-in)",
                "endpoint": DEMO_ENDPOINT,
                "security_policy": "None",
                "username": None,
                "password": None,
                "created_at": now_iso(),
            }
        )
    # seed a few default tags
    default_tags = [
        ("Plant.Temperature", "Temperature", "Double", "degC", 200),
        ("Plant.Pressure", "Pressure", "Double", "bar", 200),
        ("Plant.FlowRate", "FlowRate", "Double", "m3/h", 200),
        ("Plant.MotorSpeed", "MotorSpeed", "Double", "rpm", 100),
        ("Plant.TankLevel", "TankLevel", "Double", "%", 500),
    ]
    ns = None
    # resolve namespace index dynamically after demo server started
    if demo_server.idx is not None:
        ns = demo_server.idx
    for nid_suffix, name, dtype, unit, interval in default_tags:
        node_id = f"ns={ns};s={nid_suffix}" if ns is not None else nid_suffix
        exists = await db.opcua_tags.find_one({"server_id": DEMO_SERVER_ID, "name": name})
        if not exists:
            await db.opcua_tags.insert_one(
                {
                    "id": str(uuid.uuid4()),
                    "server_id": DEMO_SERVER_ID,
                    "node_id": node_id,
                    "name": name,
                    "data_type": dtype,
                    "unit": unit,
                    "sampling_interval": interval,
                    "created_at": now_iso(),
                }
            )


@fastapi_app.on_event("startup")
async def on_startup():
    try:
        await demo_server.start()
    except Exception as e:  # noqa
        logger.error(f"Failed to start demo OPC UA server: {e}")
    await _seed_demo()
    # auto-connect the built-in demo server for instant runtime
    cfg = await db.opcua_servers.find_one({"id": DEMO_SERVER_ID}, {"_id": 0})
    if cfg:
        await _connect_server(cfg)


@fastapi_app.on_event("shutdown")
async def on_shutdown():
    runtime["active"] = False
    for link in (runtime["link"], sink_state["link"]):
        if link:
            link.close()
    for sid in list(connections.keys()):
        await _disconnect_server(sid)
    await demo_server.stop()
    await sink_server.stop()
    mongo_client.close()


fastapi_app.include_router(api_router)
fastapi_app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

# Wrap with Socket.IO ASGI app (mounted at /api/socket.io)
app = socketio.ASGIApp(sio, other_asgi_app=fastapi_app, socketio_path="/api/socket.io")
