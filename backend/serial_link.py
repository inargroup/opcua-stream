"""Serial-port link between Sender and Receiver (works on Raspberry Pi UART / USB-serial and Windows COM ports).

Wire frame: SYNC(0xA5 0x5A) | fmt(1: 0=json,1=msgpack,2=control) | length(4, BE) | payload | crc32(4, BE over fmt+length+payload)
"""
import asyncio
import glob
import logging
import os
import queue
import threading
import time
import zlib

import serial
from serial.tools import list_ports

logger = logging.getLogger("serial_link")

SYNC = b"\xA5\x5A"
FMT_CODES = {"json": 0, "msgpack": 1, "control": 2}
FMT_NAMES = {v: k for k, v in FMT_CODES.items()}
MAX_PAYLOAD = 1_000_000
BAUD_RATES = [9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600, 1000000, 2000000]


def list_serial_ports():
    found = {}
    for p in list_ports.comports():
        found[p.device] = p.description or p.device
    for pattern in ("/dev/serial[0-9]", "/dev/ttyAMA*", "/dev/ttyUSB*", "/dev/ttyACM*", "/dev/ttyS0"):
        for dev in glob.glob(pattern):
            found.setdefault(dev, os.path.realpath(dev) if os.path.islink(dev) else dev)
    return [{"device": d, "description": desc} for d, desc in sorted(found.items())]


def encode_frame(payload: bytes, fmt: str) -> bytes:
    body = bytes([FMT_CODES[fmt]]) + len(payload).to_bytes(4, "big") + payload
    return SYNC + body + zlib.crc32(body).to_bytes(4, "big")


class FrameDecoder:
    """Stream decoder that re-synchronises on SYNC and validates CRC."""

    def __init__(self):
        self.buf = bytearray()
        self.crc_errors = 0

    def feed(self, data: bytes):
        self.buf.extend(data)
        out = []
        while True:
            i = self.buf.find(SYNC)
            if i < 0:
                del self.buf[: max(0, len(self.buf) - 1)]
                return out
            if i:
                del self.buf[:i]
            if len(self.buf) < 7:
                return out
            fmt_code = self.buf[2]
            length = int.from_bytes(self.buf[3:7], "big")
            if fmt_code not in FMT_NAMES or length > MAX_PAYLOAD:
                del self.buf[:1]
                continue
            total = 7 + length + 4
            if len(self.buf) < total:
                return out
            body = bytes(self.buf[2 : 7 + length])
            crc = int.from_bytes(self.buf[7 + length : total], "big")
            if zlib.crc32(body) != crc:
                self.crc_errors += 1
                del self.buf[:1]
                continue
            out.append((FMT_NAMES[fmt_code], body[5:], total))
            del self.buf[:total]


class _Link:
    def __init__(self, port: str, baudrate: int):
        self.port = port
        self.baudrate = baudrate
        self.ser = None
        self.error = None
        self._stop = threading.Event()
        self._thread = None

    def open(self):
        self.ser = serial.Serial(self.port, self.baudrate, timeout=0.1, write_timeout=1)
        self.error = None

    def _reopen(self):
        try:
            if self.ser:
                self.ser.close()
        except Exception:
            pass
        self.ser = None
        while not self._stop.is_set():
            try:
                self.open()
                logger.info(f"Serial {self.port} reopened")
                return True
            except Exception as e:
                self.error = str(e)
                time.sleep(1.0)
        return False

    @property
    def connected(self):
        return self.ser is not None and self.error is None

    def close(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        try:
            if self.ser:
                self.ser.close()
        except Exception:
            pass
        self.ser = None


class SerialSender(_Link):
    """Non-blocking writer: frames are queued and written by a background thread; overflow is dropped."""

    def __init__(self, port, baudrate, max_queue=64):
        super().__init__(port, baudrate)
        self.q = queue.Queue(maxsize=max_queue)
        self.dropped = 0
        self.bytes_written = 0

    def start(self):
        self.open()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def send(self, payload: bytes, fmt: str):
        try:
            self.q.put_nowait(encode_frame(payload, fmt))
        except queue.Full:
            self.dropped += 1

    def _run(self):
        while not self._stop.is_set():
            try:
                data = self.q.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                self.ser.write(data)
                self.bytes_written += len(data)
            except Exception as e:
                self.error = str(e)
                logger.warning(f"Serial write failed on {self.port}: {e}")
                self._reopen()

    def flush_and_close(self, timeout=1.5):
        end = time.time() + timeout
        while not self.q.empty() and time.time() < end:
            time.sleep(0.02)
        try:
            if self.ser:
                self.ser.flush()
        except Exception:
            pass
        self.close()


class SerialReceiver(_Link):
    """Reads frames in a background thread and hands them to an asyncio queue."""

    def __init__(self, port, baudrate, loop: asyncio.AbstractEventLoop, out: asyncio.Queue):
        super().__init__(port, baudrate)
        self.loop = loop
        self.out = out
        self.decoder = FrameDecoder()

    def start(self):
        self.open()
        try:
            self.ser.reset_input_buffer()
        except Exception:
            pass
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        while not self._stop.is_set():
            try:
                data = self.ser.read(self.ser.in_waiting or 1)
            except Exception as e:
                self.error = str(e)
                logger.warning(f"Serial read failed on {self.port}: {e}")
                self._reopen()
                continue
            if not data:
                continue
            for frame in self.decoder.feed(data):
                self.loop.call_soon_threadsafe(self.out.put_nowait, frame)
