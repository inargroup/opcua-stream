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
    const [port, setPort] = useState(9800);

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

    useEffect(() => {
        refreshServers();
        refreshTags();
        api.getRuntime().then((s) => {
            setStats(s);
            setFormatState(s.format);
        }).catch(() => {});
        api.getSink().then((s) => {
            setSinkStats(s);
            if (s.port) setPort(s.port);
        }).catch(() => {});
        api.listSinkTags().then((rows) => {
            const now = Date.now();
            rows.forEach((r) => {
                sinkValuesRef.current[r.name] = { name: r.name, value: r.value, quality: r.quality, count: r.sample_count, firstSeen: now, lastTs: r.last_update };
            });
            sinkDirtyRef.current = true;
        }).catch(() => {});
    }, [refreshServers, refreshTags]);

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
            const entry = { key: sinkFrameCounterRef.current, seq: f.seq, ts: f.ts, format: f.format, byte_size: f.byte_size, tag_count: f.tag_count, new_tags: f.new_tags };
            sinkFramesRef.current = sinkFramesRef.current.concat(entry).slice(-60);
            sinkDirtyRef.current = true;
        });
        return () => {
            if (socketRef.current?.connected) socketRef.current.disconnect();
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
        const s = await api.startRuntime(format);
        setStats(s);
        toast.success(`Transmission started · ${format.toUpperCase()}`);
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
        sinkValuesRef.current = {};
        sinkHistoryRef.current = {};
        sinkFramesRef.current = [];
        sinkFrameCounterRef.current = 0;
        setSinkTags([]);
        setSinkHistory({});
        setSinkFrameLog([]);
        try {
            const s = await api.startSink(Number(port) || 9800);
            setSinkStats(s);
            toast.success(`Receiver listening on port ${s.port}`);
        } catch (e) {
            toast.error(e?.response?.data?.detail || "Could not start receiver");
        }
    };
    const handleSinkStop = async () => {
        const s = await api.stopSink();
        setSinkStats(s);
        toast("Receiver stopped");
    };
    const handleStartSource = async () => {
        await handleStart();
    };

    return (
        <div className="min-h-screen bg-background text-foreground">
            <Toaster position="bottom-right" theme="dark" richColors />
            <StatsBar mode={mode} setMode={setMode} servers={servers} tags={tags} stats={stats} wsConnected={wsConnected} />
            <main className="px-4 md:px-6 pb-10 max-w-[1600px] mx-auto">
                {mode === "config" && (
                    <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
                        <div className="lg:col-span-4">
                            <ServerManager servers={servers} refreshServers={refreshServers} refreshTags={refreshTags} />
                        </div>
                        <div className="lg:col-span-8">
                            <TagBrowser servers={servers} tags={tags} refreshTags={refreshTags} />
                        </div>
                    </div>
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
                        port={port}
                        setPort={setPort}
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
