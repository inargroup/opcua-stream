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
}

# ---- Sink / receiver state ----
sink_server = SinkOPCUAServer()
sink_state = {
    "running": False,
    "port": None,
    "tcp_server": None,
    "frames_received": 0,
    "bytes_received": 0,
    "started_at": None,
    "_win_start": 0.0,
    "_win_frames": 0,
    "_win_bytes": 0,
    "_last_stats": 0.0,
    "fps": 0.0,
    "bps": 0.0,
    "last_seq": 0,
}
sink_data = {"tags": {}}  # name -> {name,value,quality,sample_count,first_seen,last_update}
_ingest_writer = None


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


class FormatSet(BaseModel):
    format: str


class SinkStart(BaseModel):
    port: int = 9800


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
    return {
        "active": runtime["active"],
        "format": runtime["format"],
        "frames_total": runtime["frames_total"],
        "bytes_total": runtime["bytes_total"],
        "fps": round(runtime["fps"], 1),
        "bps": round(runtime["bps"], 1),
        "uptime": round(uptime, 1),
        "active_tag_count": runtime["active_tag_count"],
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
                due_samples.append(
                    {
                        "tag_id": tag["id"],
                        "name": tag["name"],
                        "node_id": tag["node_id"],
                        "server_id": tag["server_id"],
                        "unit": tag.get("unit"),
                        "value": val,
                        "quality": quality,
                    }
                )

        if due_samples:
            runtime["seq"] += 1
            core = {
                "seq": runtime["seq"],
                "ts": now_iso(),
                "samples": [{"n": s["name"], "v": s["value"], "q": s["quality"]} for s in due_samples],
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

            if sink_state["running"]:
                await _forward_to_ingest(packed, fmt)

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
# Sink / Receiver — ingest serialized stream over a TCP port and re-publish
# on a dynamic OPC UA server.
# ---------------------------------------------------------------------------
def _sink_status():
    uptime = (time.time() - sink_state["started_at"]) if sink_state["started_at"] else 0
    return {
        "running": sink_state["running"],
        "port": sink_state["port"],
        "opcua_endpoint": sink_server.endpoint,
        "frames_received": sink_state["frames_received"],
        "bytes_received": sink_state["bytes_received"],
        "fps": round(sink_state["fps"], 1),
        "bps": round(sink_state["bps"], 1),
        "tag_count": len(sink_data["tags"]),
        "last_seq": sink_state["last_seq"],
        "uptime": round(uptime, 1),
    }


async def _forward_to_ingest(packed: bytes, fmt: str):
    """Transmit a serialized frame to the configured ingest TCP port (loopback)."""
    global _ingest_writer
    try:
        if _ingest_writer is None:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection("127.0.0.1", sink_state["port"]), timeout=1.0
            )
            _ingest_writer = writer
        fmt_byte = b"\x00" if fmt == "json" else b"\x01"
        header = len(packed).to_bytes(4, "big") + fmt_byte
        _ingest_writer.write(header + packed)
        await _ingest_writer.drain()
    except Exception:
        try:
            if _ingest_writer:
                _ingest_writer.close()
        except Exception:
            pass
        _ingest_writer = None


async def _process_received(core: dict, fmt: str, size: int):
    seq = core.get("seq")
    ts = core.get("ts")
    samples = core.get("samples", [])
    now = time.time()
    new_tags = []
    out_samples = []
    for s in samples:
        name = s.get("n")
        val = s.get("v")
        q = s.get("q")
        if name is None:
            continue
        is_new = name not in sink_data["tags"]
        await sink_server.upsert(name, val)
        rec = sink_data["tags"].get(name)
        if rec is None:
            rec = {"name": name, "value": val, "quality": q, "sample_count": 0, "first_seen": now_iso(), "last_update": None}
            sink_data["tags"][name] = rec
            new_tags.append(name)
        rec["value"] = val
        rec["quality"] = q
        rec["sample_count"] += 1
        rec["last_update"] = ts
        out_samples.append({"name": name, "value": val, "quality": q, "is_new": is_new})

    sink_state["frames_received"] += 1
    sink_state["bytes_received"] += size
    sink_state["_win_frames"] += 1
    sink_state["_win_bytes"] += size
    sink_state["last_seq"] = seq

    await sio.emit(
        "sink_frame",
        {"seq": seq, "ts": ts, "format": fmt, "byte_size": size, "tag_count": len(out_samples), "samples": out_samples, "new_tags": new_tags},
    )

    if now - sink_state["_last_stats"] >= 0.5:
        win = now - sink_state["_win_start"]
        if win > 0:
            sink_state["fps"] = sink_state["_win_frames"] / win
            sink_state["bps"] = sink_state["_win_bytes"] / win
        sink_state["_win_start"] = now
        sink_state["_win_frames"] = 0
        sink_state["_win_bytes"] = 0
        sink_state["_last_stats"] = now
        await sio.emit("sink_stats", _sink_status())


async def _handle_ingest(reader, writer):
    peer = writer.get_extra_info("peername")
    logger.info(f"Ingest connection from {peer}")
    try:
        while True:
            header = await reader.readexactly(5)
            length = int.from_bytes(header[:4], "big")
            fmt = "json" if header[4] == 0 else "msgpack"
            payload = await reader.readexactly(length)
            try:
                core = json.loads(payload) if fmt == "json" else msgpack.unpackb(payload, raw=False)
                await _process_received(core, fmt, length + 5)
            except Exception as e:  # noqa
                logger.warning(f"ingest decode failed: {e}")
    except asyncio.IncompleteReadError:
        pass
    except Exception as e:  # noqa
        logger.debug(f"ingest handler ended: {e}")
    finally:
        try:
            writer.close()
        except Exception:
            pass


@api_router.get("/sink")
async def get_sink():
    return _sink_status()


@api_router.get("/sink/tags")
async def get_sink_tags():
    return sorted(sink_data["tags"].values(), key=lambda r: r["first_seen"])


@api_router.post("/sink/start")
async def start_sink(body: SinkStart):
    global _ingest_writer
    if sink_state["running"]:
        return _sink_status()
    if not (1 <= body.port <= 65535):
        raise HTTPException(400, "Invalid port")
    await sink_server.start()
    await sink_server.reset()
    sink_data["tags"] = {}
    try:
        tcp_server = await asyncio.start_server(_handle_ingest, "0.0.0.0", body.port)
    except Exception as e:  # noqa
        raise HTTPException(502, f"Could not bind ingest port {body.port}: {e}")
    _ingest_writer = None
    sink_state.update(
        running=True,
        port=body.port,
        tcp_server=tcp_server,
        frames_received=0,
        bytes_received=0,
        started_at=time.time(),
        _win_start=time.time(),
        _win_frames=0,
        _win_bytes=0,
        _last_stats=time.time(),
        fps=0.0,
        bps=0.0,
        last_seq=0,
    )
    logger.info(f"Sink ingest listening on 0.0.0.0:{body.port}")
    await sio.emit("sink_stats", _sink_status())
    return _sink_status()


@api_router.post("/sink/stop")
async def stop_sink():
    global _ingest_writer
    if _ingest_writer:
        try:
            _ingest_writer.close()
        except Exception:
            pass
        _ingest_writer = None
    if sink_state["tcp_server"]:
        sink_state["tcp_server"].close()
        try:
            await sink_state["tcp_server"].wait_closed()
        except Exception:
            pass
    sink_state.update(running=False, tcp_server=None, started_at=None, fps=0.0, bps=0.0)
    await sio.emit("sink_stats", _sink_status())
    return _sink_status()


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
    if sink_state["tcp_server"]:
        sink_state["tcp_server"].close()
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
