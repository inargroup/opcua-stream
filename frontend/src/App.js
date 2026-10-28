import { useEffect, useRef, useState, useCallback } from "react";
import { io } from "socket.io-client";
import "@/App.css";
import { BACKEND_URL } from "@/lib/api";
import * as api from "@/lib/api";
import StatsBar from "@/components/opcua/StatsBar";
import ServerManager from "@/components/opcua/ServerManager";
import TagBrowser from "@/components/opcua/TagBrowser";
import RuntimeDashboard from "@/components/opcua/RuntimeDashboard";
import SerialMonitor from "@/components/opcua/SerialMonitor";
import ReceiverView from "@/components/opcua/ReceiverView";
import ConfigTransfer from "@/components/opcua/ConfigTransfer";
import { Toaster } from "@/components/ui/sonner";
import { toast } from "sonner";

const SOCKET_PATH = "/api/socket.io";
const HISTORY_LEN = 40;

const EMPTY_STATS = {
    active: false,
    format: "json",
    frames_total: 0,
    bytes_total: 0,
    fps: 0,
    bps: 0,
    uptime: 0,
    active_tag_count: 0,
};

export default function App() {
    const [mode, setMode] = useState("config");
    const [servers, setServers] = useState([]);
    const [tags, setTags] = useState([]);
    const [wsConnected, setWsConnected] = useState(false);
    const [stats, setStats] = useState(EMPTY_STATS);
    const [format, setFormatState] = useState("json");

    const [tagValues, setTagValues] = useState({});
    const [tagHistory, setTagHistory] = useState({});
    const [frameLog, setFrameLog] = useState([]);

    // sink / receiver
    const [sinkStats, setSinkStats] = useState({ running: false, opcua_endpoint: "", frames_received: 0, bytes_received: 0, fps: 0, bps: 0, tag_count: 0, last_seq: 0, uptime: 0 });
    const [sinkTags, setSinkTags] = useState([]);
    const [sinkHistory, setSinkHistory] = useState({});
    const [sinkFrameLog, setSinkFrameLog] = useState([]);
    const [ports, setPorts] = useState([]);
    const [bauds, setBauds] = useState([9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600]);
    const [txPort, setTxPort] = useState("");
    const [txBaud, setTxBaud] = useState(115200);
    const [rxPort, setRxPort] = useState("");
    const [rxBaud, setRxBaud] = useState(115200);
    const [silenceTimeout, setSilenceTimeout] = useState(5);

    const valuesRef = useRef({});
    const historyRef = useRef({});
    const framesRef = useRef([]);
    const frameCounterRef = useRef(0);
    const dirtyRef = useRef(false);
    const socketRef = useRef(null);

    const sinkValuesRef = useRef({});
    const sinkHistoryRef = useRef({});
    const sinkFramesRef = useRef([]);
    const sinkFrameCounterRef = useRef(0);
    const sinkDirtyRef = useRef(false);

    const refreshServers = useCallback(async () => {
        try {
            setServers(await api.listServers());
        } catch (e) {
            /* noop */
        }
    }, []);
    const refreshTags = useCallback(async () => {
        try {
            setTags(await api.listTags());
        } catch (e) {
            /* noop */
        }
    }, []);

    const refreshPorts = useCallback(async (applySettings = false) => {
        try {
            const d = await api.getSerialPorts();
            setPorts(d.ports);
            setBauds(d.baud_rates);
            if (applySettings) {
                const st = d.settings || {};
                if (st.sender_port) setTxPort(st.sender_port);
                if (st.sender_baudrate) setTxBaud(st.sender_baudrate);
                if (st.receiver_port) setRxPort(st.receiver_port);
                if (st.receiver_baudrate) setRxBaud(st.receiver_baudrate);
            }
        } catch (e) {
            /* noop */
        }
    }, []);

    useEffect(() => {
        refreshPorts(true);
        refreshServers();
        refreshTags();
        api.getRuntime().then((s) => {
            setStats(s);
            setFormatState(s.format);
        }).catch(() => {});
        api.getSink().then((s) => {
            setSinkStats(s);
            if (s.silence_timeout) setSilenceTimeout(s.silence_timeout);
            if (s.running) {
                setRxPort(s.serial_port);
                setRxBaud(s.baudrate);
            }
        }).catch(() => {});
        api.listSinkTags().then((rows) => {
            const now = Date.now();
            rows.forEach((r) => {
                sinkValuesRef.current[r.name] = { name: r.name, value: r.value, quality: r.quality, state: r.state, count: r.sample_count, firstSeen: now, lastTs: r.last_update };
            });
            sinkDirtyRef.current = true;
        }).catch(() => {});
    }, [refreshServers, refreshTags, refreshPorts]);

    // Socket.IO high-speed channel
    useEffect(() => {
        const socket = io(BACKEND_URL, { path: SOCKET_PATH, transports: ["websocket", "polling"] });
        socketRef.current = socket;
        socket.on("connect", () => setWsConnected(true));
        socket.on("disconnect", () => setWsConnected(false));
        socket.on("stats", (s) => setStats(s));
        socket.on("frame", (f) => {
            (f.samples || []).forEach((s) => {
                valuesRef.current[s.tag_id] = { ...s };
                let num = null;
                if (typeof s.value === "number") num = s.value;
                else if (s.value === true) num = 1;
                else if (s.value === false) num = 0;
                if (num !== null) {
                    const prev = historyRef.current[s.tag_id] || [];
                    const nextX = prev.length ? prev[prev.length - 1].i + 1 : 0;
                    historyRef.current[s.tag_id] = prev.concat({ i: nextX, v: num }).slice(-HISTORY_LEN);
                }
            });
            frameCounterRef.current += 1;
            const entry = {
                key: frameCounterRef.current,
                seq: f.seq,
                ts: f.ts,
                format: f.format,
                byte_size: f.byte_size,
                tag_count: f.tag_count,
                preview: f.preview,
            };
            framesRef.current = framesRef.current.concat(entry).slice(-60);
            dirtyRef.current = true;
        });
        socket.on("sink_stats", (s) => setSinkStats(s));
        socket.on("sink_frame", (f) => {
            (f.samples || []).forEach((s) => {
                const name = s.name;
                let rec = sinkValuesRef.current[name];
                if (!rec) rec = { name, count: 0, firstSeen: Date.now() };
                rec.value = s.value;
                rec.quality = s.quality;
                rec.count = (rec.count || 0) + 1;
                rec.lastTs = f.ts;
                rec.state = "active";
                if (f.revived && f.revived.includes(name)) rec.revivedUntil = Date.now() + 5000;
                if (s.is_new || (f.new_tags && f.new_tags.includes(name))) rec.newUntil = Date.now() + 5000;
                sinkValuesRef.current[name] = rec;
                let num = null;
                if (typeof s.value === "number") num = s.value;
                else if (s.value === true) num = 1;
                else if (s.value === false) num = 0;
                if (num !== null) {
                    const prev = sinkHistoryRef.current[name] || [];
                    const nextX = prev.length ? prev[prev.length - 1].i + 1 : 0;
                    sinkHistoryRef.current[name] = prev.concat({ i: nextX, v: num }).slice(-HISTORY_LEN);
                }
            });
            sinkFrameCounterRef.current += 1;
            const entry = { key: sinkFrameCounterRef.current, seq: f.seq, ts: f.ts, format: f.format, byte_size: f.byte_size, tag_count: f.tag_count, new_tags: f.new_tags, revived: f.revived };
            sinkFramesRef.current = sinkFramesRef.current.concat(entry).slice(-60);
            sinkDirtyRef.current = true;
        });
        socket.on("sink_dormant", (d) => {
            (d.names || []).forEach((name) => {
                const rec = sinkValuesRef.current[name];
                if (rec) sinkValuesRef.current[name] = { ...rec, state: "dormant", revivedUntil: 0, newUntil: 0 };
            });
            sinkFrameCounterRef.current += 1;
            const entry = { key: sinkFrameCounterRef.current, seq: 0, ts: new Date().toISOString(), format: "ctl", byte_size: 0, tag_count: 0, dormant: d.names };
            sinkFramesRef.current = sinkFramesRef.current.concat(entry).slice(-60);
            sinkDirtyRef.current = true;
        });
        return () => {
            socket.removeAllListeners();
            socket.disconnect();
        };
    }, []);

    // Throttled flush from refs -> state (~4 fps) to avoid render thrashing
    useEffect(() => {
        const id = setInterval(() => {
            if (dirtyRef.current) {
                dirtyRef.current = false;
                const histCopy = {};
                for (const k in historyRef.current) histCopy[k] = historyRef.current[k].slice();
                setTagValues({ ...valuesRef.current });
                setTagHistory(histCopy);
                setFrameLog(framesRef.current.slice());
            }
            if (sinkDirtyRef.current) {
                sinkDirtyRef.current = false;
                const sHist = {};
                for (const k in sinkHistoryRef.current) sHist[k] = sinkHistoryRef.current[k].slice();
                const rows = Object.values(sinkValuesRef.current).map((r) => ({ ...r })).sort((a, b) => a.firstSeen - b.firstSeen);
                setSinkTags(rows);
                setSinkHistory(sHist);
                setSinkFrameLog(sinkFramesRef.current.slice());
            }
        }, 250);
        return () => clearInterval(id);
    }, []);

    const handleStart = async () => {
        valuesRef.current = {};
        historyRef.current = {};
        framesRef.current = [];
        frameCounterRef.current = 0;
        setTagValues({});
        setTagHistory({});
        setFrameLog([]);
        try {
            const s = await api.startRuntime(format, txPort.trim(), txBaud);
            setStats(s);
            toast.success(`Transmission started · ${format.toUpperCase()}${s.serial_port ? ` → ${s.serial_port} @ ${s.baudrate}` : ""}`);
        } catch (e) {
            toast.error(e?.response?.data?.detail || "Could not start transmission");
        }
    };
    const handleStop = async () => {
        const s = await api.stopRuntime();
        setStats(s);
        toast("Transmission stopped");
    };
    const handleFormat = async (fmt) => {
        setFormatState(fmt);
        try {
            const s = await api.setFormat(fmt);
            setStats(s);
        } catch (e) {
            /* noop */
        }
    };

    const handleSinkStart = async () => {
        if (!rxPort.trim()) {
            toast.error("Choose the serial port the Sender is wired to");
            return;
        }
        try {
            const s = await api.startSink(rxPort.trim(), rxBaud, Number(silenceTimeout) || 5);
            sinkValuesRef.current = {};
            sinkHistoryRef.current = {};
            sinkFramesRef.current = [];
            sinkFrameCounterRef.current = 0;
            setSinkTags([]);
            setSinkHistory({});
            setSinkFrameLog([]);
            setSinkStats(s);
            toast.success(`Receiver listening on ${s.serial_port} @ ${s.baudrate}`);
        } catch (e) {
            toast.error(e?.response?.data?.detail || "Could not start receiver");
        }
    };
    const handleSinkStop = async () => {
        const s = await api.stopSink();
        setSinkStats(s);
        toast("Receiver stopped");
    };
    const handleApplySilence = async () => {
        const v = Number(silenceTimeout);
        if (!(v >= 0.5 && v <= 3600)) {
            toast.error("Silence alarm time must be between 0.5 and 3600 s");
            return;
        }
        if (!sinkStats.running || v === sinkStats.silence_timeout) return;
        try {
            setSinkStats(await api.configSink(v));
            toast.success(`Silence alarm set to ${v}s`);
        } catch (e) {
            toast.error("Could not update silence alarm");
        }
    };
    const handleImported = async (st) => {
        setFormatState(st.format);
        setSilenceTimeout(st.silence_timeout);
        setTxPort(st.sender_port || "");
        setTxBaud(st.sender_baudrate);
        setRxPort(st.receiver_port || "");
        setRxBaud(st.receiver_baudrate);
        await Promise.all([refreshServers(), refreshTags()]);
    };
    const handleStartSource = async () => {
        if (!txPort.trim()) {
            toast.error("Set the Sender's output serial port in Runtime mode first");
            return;
        }
        await handleStart();
    };

    return (
        <div className="min-h-screen bg-background text-foreground">
            <Toaster position="bottom-right" theme="dark" richColors />
            <StatsBar mode={mode} setMode={setMode} servers={servers} tags={tags} stats={stats} wsConnected={wsConnected} />
            <main className="px-4 md:px-6 pb-10 max-w-[1600px] mx-auto">
                {mode === "config" && (
                    <>
                    <ConfigTransfer busy={stats.active || sinkStats.running} onImported={handleImported} />
                    <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
                        <div className="lg:col-span-4">
                            <ServerManager servers={servers} refreshServers={refreshServers} refreshTags={refreshTags} />
                        </div>
                        <div className="lg:col-span-8">
                            <TagBrowser servers={servers} tags={tags} refreshTags={refreshTags} />
                        </div>
                    </div>
                    </>
                )}
                {mode === "runtime" && (
                    <div className="grid grid-cols-1 lg:grid-cols-12 gap-4 items-start">
                        <div className="lg:col-span-8">
                            <RuntimeDashboard tags={tags} tagValues={tagValues} tagHistory={tagHistory} stats={stats} />
                        </div>
                        <div className="lg:col-span-4">
                            <SerialMonitor
                                stats={stats}
                                format={format}
                                onStart={handleStart}
                                onStop={handleStop}
                                onFormat={handleFormat}
                                frameLog={frameLog}
                                serial={{ port: txPort, setPort: setTxPort, baud: txBaud, setBaud: setTxBaud, ports, bauds, tagCount: tags.length, onRefresh: () => refreshPorts() }}
                            />
                        </div>
                    </div>
                )}
                {mode === "receiver" && (
                    <ReceiverView
                        sinkStats={sinkStats}
                        sinkTags={sinkTags}
                        sinkHistory={sinkHistory}
                        sinkFrameLog={sinkFrameLog}
                        serial={{ port: rxPort, setPort: setRxPort, baud: rxBaud, setBaud: setRxBaud, ports, bauds, onRefresh: () => refreshPorts() }}
                        silenceTimeout={silenceTimeout}
                        setSilenceTimeout={setSilenceTimeout}
                        onApplySilence={handleApplySilence}
                        onStart={handleSinkStart}
                        onStop={handleSinkStop}
                        runtimeActive={stats.active}
                        onStartSource={handleStartSource}
                    />
                )}
            </main>
        </div>
    );
}
