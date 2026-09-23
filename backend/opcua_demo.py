"""Built-in simulated OPC UA server exposing industrial process tags.

Runs inside the backend process so the client can perform a genuine
end-to-end OPC UA session against opc.tcp://127.0.0.1:4840.
"""
import asyncio
import logging
import math
import random
import time

from asyncua import Server, ua

logger = logging.getLogger("opcua_demo")

# name, engineering unit, kind, initial value
TAG_SPECS = [
    ("Temperature", "degC", "sine", 65.0),
    ("Pressure", "bar", "sine", 4.0),
    ("FlowRate", "m3/h", "sine", 120.0),
    ("MotorSpeed", "rpm", "sine", 1450.0),
    ("TankLevel", "%", "sine", 55.0),
    ("Vibration", "mm/s", "noise", 2.0),
    ("PowerConsumption", "kW", "sine", 75.0),
    ("ValvePosition", "%", "ramp", 0.0),
    ("PumpStatus", "bool", "bool", True),
    ("ProductionCount", "units", "counter", 0),
    ("QualityIndex", "%", "int", 98),
]


class DemoOPCUAServer:
    def __init__(self, endpoint="opc.tcp://127.0.0.1:4840/emergent/server/"):
        self.endpoint = endpoint
        self.server = None
        self.idx = None
        self.nodes = {}
        self._task = None
        self._running = False

    async def start(self):
        self.server = Server()
        await self.server.init()
        self.server.set_endpoint(self.endpoint)
        self.server.set_server_name("Emergent Demo OPC UA Server")
        self.server.set_security_policy([ua.SecurityPolicyType.NoSecurity])

        self.idx = await self.server.register_namespace("http://emergent.demo/opcua")
        objects = self.server.nodes.objects
        plant = await objects.add_object(ua.NodeId("Plant", self.idx), ua.QualifiedName("Plant", self.idx))

        for name, unit, kind, init in TAG_SPECS:
            nodeid = ua.NodeId(f"Plant.{name}", self.idx)
            bname = ua.QualifiedName(name, self.idx)
            var = await plant.add_variable(nodeid, bname, init)
            await var.set_writable()
            self.nodes[name] = {"node": var, "kind": kind, "unit": unit}

        await self.server.start()
        self._running = True
        self._task = asyncio.create_task(self._update_loop())
        logger.info(f"Demo OPC UA server started at {self.endpoint}")

    async def _update_loop(self):
        t0 = time.time()
        counter = 0
        while self._running:
            t = time.time() - t0
            counter += 1
            for name, meta in self.nodes.items():
                kind = meta["kind"]
                try:
                    if kind == "sine":
                        base = dict(TAG_SPECS_MAP)[name]
                        amp = base * 0.2
                        val = round(base + amp * math.sin(t / (2 + (hash(name) % 7))) + random.uniform(-amp * 0.05, amp * 0.05), 2)
                        await meta["node"].write_value(float(val))
                    elif kind == "noise":
                        val = round(2.0 + abs(math.sin(t)) * 3.0 + random.uniform(0, 0.6), 3)
                        await meta["node"].write_value(float(val))
                    elif kind == "ramp":
                        val = round((t * 5) % 100, 1)
                        await meta["node"].write_value(float(val))
                    elif kind == "bool":
                        await meta["node"].write_value(bool(int(t / 5) % 2 == 0))
                    elif kind == "counter":
                        await meta["node"].write_value(ua.Variant(counter, ua.VariantType.Int64))
                    elif kind == "int":
                        await meta["node"].write_value(ua.Variant(int(95 + 5 * math.sin(t / 4)), ua.VariantType.Int64))
                except Exception as e:  # noqa
                    logger.warning(f"update {name} failed: {e}")
            await asyncio.sleep(0.2)

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
        if self.server:
            await self.server.stop()
        logger.info("Demo OPC UA server stopped")


TAG_SPECS_MAP = {name: init for name, unit, kind, init in TAG_SPECS}
