# OPC//STREAM — OPC UA Sender / Receiver over Serial

Samples tags from multiple OPC UA servers, serializes them (JSON or MessagePack) and transmits them over a
**serial port** to a Receiver that re-publishes them on its own OPC UA server (`opc.tcp://<device-ip>:4841/emergent/sink/`).

## Topology
```
[Sender Pi] --- serial cable (TX->RX, RX->TX, GND->GND) --- [Receiver Pi]
 Runtime mode: pick output port + baud           Receiver mode: pick input port + same baud
```
Both devices run the same app. Use the **same baud rate** on both sides.

## Serial frame format
`A5 5A | fmt (0=json,1=msgpack,2=control) | length (4B BE) | payload | CRC32 (4B BE)` — the Receiver
re-synchronises on noise and counts CRC errors. When the Sender stops it sends a control frame and the
Receiver immediately marks all tags **DORMANT** (last value kept, OPC UA status `Uncertain_LastUsableValue`).
Tags also turn dormant after ~3 s (or 3× their sampling interval) of silence. When the Sender restarts,
the existing tags are **revived** — no duplicate nodes are created.

## Raspberry Pi OS install
```bash
git clone <your-repo> opc-stream && cd opc-stream
bash scripts/raspberry-pi/install.sh
```
- GPIO UART: `sudo raspi-config` → Interface Options → Serial Port → login shell **No**, hardware **Yes**, reboot. Port: `/dev/serial0`.
- USB-serial adapters appear as `/dev/ttyUSB0` / `/dev/ttyACM0`.
- MongoDB: Pi 5 runs `mongo:7`; Pi 4 (ARMv8.0) only supports up to `mongo:4.4.18` — the installer picks automatically.
- Bench test without cables: `bash scripts/raspberry-pi/virtual-serial-pair.sh` then use `/tmp/ttyV0` (Sender) and `/tmp/ttyV1` (Receiver).

## Throughput guide
115 200 bps ≈ 11 KB/s. If the Sender shows a rising **dropped** counter, raise the baud rate (e.g. 460 800 / 921 600 on short cables) or slow the tag sampling intervals.

## Windows
Same app; serial ports are `COM3`, `COM4`… Run backend with `uvicorn server:app --port 8001` and frontend with `yarn start`.
