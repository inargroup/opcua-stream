# OPC//STREAM — OPC UA Multi-Server Client

## Problem Statement
An OPC UA client that connects to multiple OPC UA servers. Users define source servers and the tags to be sampled. Two modes: **Configuration** and **Runtime**. In Runtime mode the app serialises and transmits the sampled data over a high-speed serial communication channel.

## User Choices
- Real `asyncua` OPC UA library + a built-in simulated demo OPC UA server (works out of the box).
- "High-speed serial channel" = high-frequency WebSocket (Socket.IO) stream.
- Serialization format selectable: **JSON** and **binary (MessagePack)**.
- Industrial **SCADA-style dark dashboard**.

## Architecture
- **Backend**: FastAPI + `python-socketio` (ASGI, path `/api/socket.io`), `asyncua` client + built-in `asyncua` demo server (`opc.tcp://127.0.0.1:4840`, 11 simulated Plant tags), `msgpack`. MongoDB stores server & tag configs.
- **Frontend**: React (CRA/craco), Tailwind + shadcn/ui, recharts sparklines, socket.io-client. Fonts: Chivo (headings), Inter (body), IBM Plex Mono (data).
- Runtime `_transmission_loop` (50ms base tick) samples due tags via real OPC UA reads, serialises each frame (JSON or MessagePack), emits `frame` + periodic `stats` over Socket.IO.

## Implemented (2026-06)
- Server Manager: CRUD, connect/disconnect (genuine OPC UA sessions), live status, tag counts. Bad endpoint → 502.
- Address-space browser: breadcrumb navigation of the OPC UA node tree with live values; add variables as sampled tags with per-tag sampling interval.
- Tag CRUD (duplicate node on same server → 409), editable interval, delete.
- Configuration ↔ Runtime mode toggle.
- Runtime dashboard: live tag tiles (value + quality + sparkline), KPI header (servers, tags, channel, frames TX, data rate, uptime).
- Serial Channel Monitor: terminal-style frame feed, JSON/MessagePack toggle (live), start/stop transmission, throughput stats.
- Built-in demo server auto-connects on startup and seeds 5 default tags.

## Test Status
- Backend: 9/9 pytest pass (CRUD, browse, runtime, Socket.IO connect/stats/frames, json vs msgpack size). `/app/backend/tests/backend_test.py`.
- Frontend: 100% (iteration_2) — runtime streaming, tiles, terminal, format toggle, stop/restart all verified on live URL.

## Backlog / Next
- P1: Add `data-testid` to individual KPI values (frames-tx, data-rate, uptime) for automation robustness.
- P1: Historical trend view / multi-tag chart overlay.
- P2: Export/import full configuration (servers + tags) as JSON.
- P2: Alarms/thresholds per tag with visual alerting.
- P2: Migrate FastAPI `on_event` startup/shutdown to lifespan handlers.
- P2: Persist runtime stats / recording to MongoDB for playback.

## Notes
- No authentication. No Socket.IO rooms/collaboration.
- Env: frontend uses `REACT_APP_BACKEND_URL`; backend uses `MONGO_URL`/`DB_NAME`. Do not hardcode.
