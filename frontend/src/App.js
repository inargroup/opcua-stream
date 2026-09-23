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

    const valuesRef = useRef({});
    const historyRef = useRef({});
    const framesRef = useRef([]);
    const dirtyRef = useRef(false);
    const socketRef = useRef(null);

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
                valuesRef.current[s.tag_id] = s;
                let num = null;
                if (typeof s.value === "number") num = s.value;
                else if (s.value === true) num = 1;
                else if (s.value === false) num = 0;
                if (num !== null) {
                    const arr = historyRef.current[s.tag_id] || [];
                    arr.push({ t: f.seq, v: num });
                    if (arr.length > HISTORY_LEN) arr.shift();
                    historyRef.current[s.tag_id] = arr;
                }
            });
            framesRef.current.push({
                seq: f.seq,
                ts: f.ts,
                format: f.format,
                byte_size: f.byte_size,
                tag_count: f.tag_count,
                preview: f.preview,
            });
            if (framesRef.current.length > 60) framesRef.current = framesRef.current.slice(-60);
            dirtyRef.current = true;
        });
        return () => {
            if (socketRef.current?.connected) socketRef.current.disconnect();
        };
    }, []);

    // Throttled flush from refs -> state (~4 fps) to avoid render thrashing
    useEffect(() => {
        const id = setInterval(() => {
            if (!dirtyRef.current) return;
            dirtyRef.current = false;
            setTagValues({ ...valuesRef.current });
            setTagHistory({ ...historyRef.current });
            setFrameLog([...framesRef.current]);
        }, 250);
        return () => clearInterval(id);
    }, []);

    const handleStart = async () => {
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

    return (
        <div className="min-h-screen bg-background text-foreground">
            <Toaster position="top-right" theme="dark" richColors />
            <StatsBar mode={mode} setMode={setMode} servers={servers} tags={tags} stats={stats} wsConnected={wsConnected} />
            <main className="px-4 md:px-6 pb-10 max-w-[1600px] mx-auto">
                {mode === "config" ? (
                    <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
                        <div className="lg:col-span-4">
                            <ServerManager servers={servers} refreshServers={refreshServers} refreshTags={refreshTags} />
                        </div>
                        <div className="lg:col-span-8">
                            <TagBrowser servers={servers} tags={tags} refreshTags={refreshTags} />
                        </div>
                    </div>
                ) : (
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
            </main>
        </div>
    );
}
