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
- **Receiver/Sink**: a second genuine `asyncua` server (`opc.tcp://127.0.0.1:4841`, `/app/backend/opcua_sink.py`) fed by a TCP ingest listener on a user-defined port. The transmitter forwards each serialized frame (4-byte length + 1-byte format flag + payload) over TCP; the sink deserializes and **dynamically creates OPC UA nodes** for any new tag (preserving bool/int/float/str types). Only the ingest port is configured.
- **Frontend**: React (CRA/craco), Tailwind + shadcn/ui, recharts sparklines, socket.io-client. Fonts: Chivo (headings), Inter (body), IBM Plex Mono (data). Three modes: Configuration / Runtime / Receiver.
- Runtime `_transmission_loop` (50ms base tick, hot-reloads tag list every 2s) samples due tags via real OPC UA reads, serialises each frame (JSON or MessagePack), emits `frame`/`stats` over Socket.IO and (when receiver running) forwards to the ingest port.

## Implemented (2026-06)
- Server Manager: CRUD, connect/disconnect (genuine OPC UA sessions), live status, tag counts. Bad endpoint → 502.
- Address-space browser: breadcrumb navigation of the OPC UA node tree with live values; add variables as sampled tags with per-tag sampling interval.
- Tag CRUD (duplicate node on same server → 409), editable interval, delete.
- Configuration ↔ Runtime mode toggle.
- Runtime dashboard: live tag tiles (value + quality + sparkline), KPI header (servers, tags, channel, frames TX, data rate, uptime).
- Serial Channel Monitor: terminal-style frame feed, JSON/MessagePack toggle (live), start/stop transmission, throughput stats.
- Built-in demo server auto-connects on startup and seeds 5 default tags.

## Implemented — Receiver / Sink (2026-06)
- **Receiver mode** (`mode-receiver-btn`): a standalone OPC UA server that ingests the serialized high-speed stream on a user-defined TCP port (default 9800) — the only configuration required.
- Dynamically auto-discovers and creates tags as new ones arrive in the stream (no pre-config); re-publishes them on `opc.tcp://127.0.0.1:4841` for external OPC UA clients (verified with a real asyncua client).
- Real-time UI: auto-appearing tag tiles (value + quality + sparkline + sample count) with a NEW badge on freshly discovered tags, live throughput stats (frames RX, rate, tags, uptime), and an inbound-frame terminal.
- Endpoints: `GET/POST /api/sink`, `/api/sink/start` `{port}`, `/api/sink/stop`, `GET /api/sink/tags`. Socket.IO events `sink_frame` + `sink_stats`.
- Data types preserved on re-publish (Boolean/Int64/Double/String).

## Implemented — Serial link + Raspberry Pi (2026-06)
- TCP Sender→Receiver link REPLACED by serial port (`backend/serial_link.py`, pyserial). Frame: `A5 5A | fmt | len32 | payload | CRC32`; resync + CRC error count; non-blocking writer queue with dropped counter; auto-reopen on port loss.
- Sender (Runtime → Serial Channel): output port + baud list (9600–2,000,000). Empty port = local only. Receiver: input port + baud. Last ports saved in Mongo `app_settings` (`GET /api/serial/ports`).
- Dormant tags: Sender stop sends control frame → all receiver tags DORMANT (last value kept, OPC UA status `UncertainLastUsableValue`); silence > max(3s, 3×sampling interval) also → dormant. Sender restart revives the same nodes (no duplicates). Receiver restart resets tags (user choice).
- Sink OPC UA endpoint now binds `0.0.0.0:4841`. Bad port → 409.
- Pi deliverables: `scripts/raspberry-pi/install.sh` (venv, yarn build, Mongo via Docker 4.4.18/7, dialout, systemd + nginx), `virtual-serial-pair.sh` (socat bench test), README.
- Tested iteration_4: backend 6/6 (`backend/tests/test_serial_sink.py`), frontend flows pass; fixed StrictMode double socket, 502→409, false early dormancy, reset-before-validate.

## Implemented — Link Health, Speed Advisor, Config File (2026-06)
- Receiver alarm banner (`link-alarm-banner`): `line_silent` (configurable silence time 0.5–3600 s, live via `POST /api/sink/config`; suppressed after a clean Sender stop), `crc_errors` (any CRC error in last 10 s), `link_lost`. LINK stat shows OK/SILENT/NOISY/LOST.
- Sender Speed Advisor: `GET /api/runtime/estimate?format&baudrate` simulates 10 s of the scheduler → load %, ok/tight/overloaded, suggested baud (≤70 % load); one-click apply. Warn only, never blocks.
- Config download/upload: `GET /api/config/export`, `POST /api/config/import` (replace-all; servers, tags, serial ports/baud, format, silence time; passwords never exported, kept when id+endpoint+username unchanged, otherwise listed in `password_needed`). Blocked (409) while transmitting/receiving. Demo seed skipped after an import. Format + silence time persisted in `app_settings`.
- Fixes: receiver drains 300 ms on open (stale frames); estimate validates baud; `/api/servers` no longer returns passwords.
- Tested: iteration_5 (19/19), iteration_6 (21/21 + frontend).

## Test Status
- Backend: 9/9 pytest pass (CRUD, browse, runtime, Socket.IO connect/stats/frames, json vs msgpack size). `/app/backend/tests/backend_test.py`.
- Frontend: 100% (iteration_2) — runtime streaming, tiles, terminal, format toggle, stop/restart all verified on live URL.

## Backlog / Next
- P1: Verify on real Raspberry Pi hardware (UART /dev/serial0 and USB adapters).
- P1: Optional RS-485 half-duplex (DE/RE pin) support.
- P1: Add `data-testid` to individual KPI values (frames-tx, data-rate, uptime) for automation robustness.
- P1: Historical trend view / multi-tag chart overlay.

- P2: Alarms/thresholds per tag with visual alerting.
- P2: Migrate FastAPI `on_event` startup/shutdown to lifespan handlers.
- P2: Persist runtime stats / recording to MongoDB for playback.

## Notes
- No authentication. No Socket.IO rooms/collaboration.
- Env: frontend uses `REACT_APP_BACKEND_URL`; backend uses `MONGO_URL`/`DB_NAME`. Do not hardcode.
