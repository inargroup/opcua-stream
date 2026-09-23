"""Sink side: an OPC UA server that ingests the serialized high-speed stream.

- Listens on a user-defined TCP port for length-prefixed serialized frames
  (4-byte big-endian length + 1-byte format flag [0=json,1=msgpack] + payload).
- Deserializes each frame and DYNAMICALLY creates / updates OPC UA variable
  nodes under a "Received" folder — no prior configuration of tags required.
- Re-exposes everything on a genuine OPC UA server endpoint so external
  OPC UA clients could subscribe to the received data.
"""
import logging

from asyncua import Server, ua

logger = logging.getLogger("opcua_sink")


def _norm(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return float(value)
    return str(value)


class SinkOPCUAServer:
    def __init__(self, endpoint="opc.tcp://127.0.0.1:4841/emergent/sink/"):
        self.endpoint = endpoint
        self.server = None
        self.idx = None
        self.folder = None
        self.nodes = {}  # name -> Variable node

    async def start(self):
        if self.server is not None:
            return
        self.server = Server()
        await self.server.init()
        self.server.set_endpoint(self.endpoint)
        self.server.set_server_name("Emergent Sink OPC UA Server")
        self.server.set_security_policy([ua.SecurityPolicyType.NoSecurity])
        self.idx = await self.server.register_namespace("http://emergent.sink/opcua")
        self.folder = await self.server.nodes.objects.add_object(
            ua.NodeId("Received", self.idx), ua.QualifiedName("Received", self.idx)
        )
        await self.server.start()
        logger.info(f"Sink OPC UA server started at {self.endpoint}")

    async def reset(self):
        """Drop all dynamically created nodes (called when a new ingest session starts)."""
        for name, node in list(self.nodes.items()):
            try:
                await self.server.delete_nodes([node])
            except Exception:
                pass
        self.nodes = {}

    async def upsert(self, name, value):
        """Create the variable node on first sight, otherwise write the new value.

        Returns True if a new node was dynamically created.
        """
        v = _norm(value)
        if name in self.nodes:
            try:
                await self.nodes[name].write_value(v)
            except Exception as e:  # type drift etc.
                logger.debug(f"write {name} failed: {e}")
            return False
        nodeid = ua.NodeId(f"Received.{name}", self.idx)
        var = await self.folder.add_variable(nodeid, ua.QualifiedName(name, self.idx), v)
        self.nodes[name] = var
        logger.info(f"Sink dynamically added tag: {name}")
        return True

    async def stop(self):
        if self.server:
            try:
                await self.server.stop()
            except Exception:
                pass
        self.server = None
        self.nodes = {}
