"""Sink side: an OPC UA server that ingests the serialized high-speed stream.

- Frames arrive over a serial port (see serial_link.py).
- Deserializes each frame and DYNAMICALLY creates / updates OPC UA variable
  nodes under a "Received" folder — no prior configuration of tags required.
- Re-exposes everything on a genuine OPC UA server endpoint so external
  OPC UA clients could subscribe to the received data.
"""
import logging

from asyncua import Server, ua

logger = logging.getLogger("opcua_sink")


def _norm(value):
    """Preserve OPC UA data-type semantics on the re-published server:
    bool -> Boolean, int -> Int64, float -> Double, everything else -> String.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return float(value)
    return str(value)


VTYPES = {"bool": ua.VariantType.Boolean, "int": ua.VariantType.Int64, "float": ua.VariantType.Double, "str": ua.VariantType.String}


class SinkOPCUAServer:
    def __init__(self, endpoint="opc.tcp://0.0.0.0:4841/emergent/sink/"):
        self.endpoint = endpoint
        self.server = None
        self.idx = None
        self.folder = None
        self.nodes = {}  # name -> Variable node
        self.kinds = {}  # name -> 'bool'|'int'|'float'|'str'
        self.last = {}  # name -> last written value

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
        self.kinds = {}
        self.last = {}

    async def _write(self, name, value, status):
        dv = ua.DataValue(ua.Variant(value, VTYPES[self.kinds[name]]), StatusCode=ua.StatusCode(status))
        await self.nodes[name].write_value(dv)

    async def set_dormant(self, name):
        """Keep the last value but flag it Uncertain_LastUsableValue for OPC UA clients."""
        if name in self.nodes:
            try:
                await self._write(name, self.last[name], ua.StatusCodes.UncertainLastUsableValue)
            except Exception as e:
                logger.debug(f"dormant {name} failed: {e}")

    def _coerce(self, name, value):
        kind = self.kinds.get(name)
        try:
            if kind == "bool":
                return bool(value)
            if kind == "int":
                return int(round(value)) if isinstance(value, float) else int(value)
            if kind == "float":
                return float(value)
            if kind == "str":
                return str(value)
        except Exception:
            pass
        return _norm(value)

    async def upsert(self, name, value):
        """Create the variable node on first sight, otherwise write the new value.

        Returns True if a new node was dynamically created.
        """
        if name in self.nodes:
            try:
                if value is None:
                    await self._write(name, self.last[name], ua.StatusCodes.BadNoCommunication)
                else:
                    v = self._coerce(name, value)
                    await self._write(name, v, ua.StatusCodes.Good)
                    self.last[name] = v
            except Exception as e:  # type drift etc.
                logger.debug(f"write {name} failed: {e}")
            return False
        v = _norm(value)
        self.kinds[name] = "bool" if isinstance(value, bool) else "int" if isinstance(value, int) else "float" if isinstance(value, float) else "str"
        nodeid = ua.NodeId(f"Received.{name}", self.idx)
        var = await self.folder.add_variable(nodeid, ua.QualifiedName(name, self.idx), v)
        self.nodes[name] = var
        self.last[name] = v
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
