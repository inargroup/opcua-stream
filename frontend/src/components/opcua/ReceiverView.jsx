import { useEffect, useRef } from "react";
import { LineChart, Line, YAxis, ResponsiveContainer } from "recharts";
import { Inbox, Square, Power, PlugZap, Sparkles, ArrowDownToLine, Moon, RotateCcw } from "lucide-react";
import SerialPortPicker from "@/components/opcua/SerialPortPicker";

const fmtBytes = (b) => {
    if (b > 1048576) return `${(b / 1048576).toFixed(2)} MB`;
    if (b > 1024) return `${(b / 1024).toFixed(1)} KB`;
    return `${b | 0} B`;
};
const fmtValue = (v) => {
    if (v === null || v === undefined) return "—";
    if (typeof v === "boolean") return v ? "ON" : "OFF";
    if (typeof v === "number") return Number.isInteger(v) ? v.toLocaleString() : v.toFixed(2);
    return String(v);
};
const fmtTime = (iso) => {
    try {
        const d = new Date(iso);
        return d.toLocaleTimeString("en-GB", { hour12: false }) + "." + String(d.getMilliseconds()).padStart(3, "0");
    } catch {
        return "";
    }
};

function Sparkline({ data }) {
    if (!data || data.length < 2) return <div className="h-9 w-full" />;
    return (
        <div className="h-9 w-full">
            <ResponsiveContainer width="100%" height="100%">
                <LineChart data={data} margin={{ top: 2, bottom: 2, left: 0, right: 0 }}>
                    <YAxis hide domain={["dataMin", "dataMax"]} />
                    <Line type="monotone" dataKey="v" stroke="#00E5FF" strokeWidth={1.5} dot={false} isAnimationActive={false} />
                </LineChart>
            </ResponsiveContainer>
        </div>
    );
}

function TileBadge({ isNew, revived, dormant, good }) {
    if (dormant)
        return (
            <span className="text-[9px] font-mono px-1.5 py-0.5 rounded bg-amber-400/10 text-amber-400 flex items-center gap-1 shrink-0">
                <Moon className="h-2.5 w-2.5" /> DORMANT
            </span>
        );
    if (isNew)
        return (
            <span className="text-[9px] font-mono px-1.5 py-0.5 rounded bg-primary/15 text-primary flex items-center gap-1 shrink-0 animate-livepulse">
                <Sparkles className="h-2.5 w-2.5" /> NEW
            </span>
        );
    if (revived)
        return (
            <span className="text-[9px] font-mono px-1.5 py-0.5 rounded bg-emerald-400/15 text-emerald-300 flex items-center gap-1 shrink-0 animate-livepulse">
                <RotateCcw className="h-2.5 w-2.5" /> REVIVED
            </span>
        );
    return (
        <span className={`text-[9px] font-mono px-1.5 py-0.5 rounded shrink-0 ${good ? "bg-emerald-400/10 text-emerald-400" : "bg-red-500/10 text-red-400"}`}>
            {good ? "GOOD" : "BAD"}
        </span>
    );
}

function ReceivedTile({ rec, history }) {
    const isNew = rec.newUntil && Date.now() < rec.newUntil;
    const revived = rec.revivedUntil && Date.now() < rec.revivedUntil;
    const dormant = rec.state === "dormant";
    const good = rec.quality === 192;
    return (
        <div
            className={`rounded-md border bg-card p-4 flex flex-col gap-2 transition-all duration-300 ${
                dormant ? "border-amber-400/30 opacity-60 grayscale" : isNew ? "border-primary shadow-[0_0_0_1px_rgba(0,229,255,0.4)]" : "border-border hover:border-primary/40"
            }`}
            data-testid={`received-tile-${rec.name}`}
            data-state={dormant ? "dormant" : "active"}
        >
            <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                    <p className="text-sm font-medium truncate">{rec.name}</p>
                    <p className="font-mono text-[10px] text-muted-foreground truncate">ns=?;s=Received.{rec.name}</p>
                </div>
                <span data-testid={`received-state-${rec.name}`}>
                    <TileBadge isNew={isNew} revived={revived} dormant={dormant} good={good} />
                </span>
            </div>
            <div className="flex items-end gap-1">
                <span className="font-mono tabular-nums text-2xl font-semibold text-primary leading-none" data-testid={`received-value-${rec.name}`}>
                    {fmtValue(rec.value)}
                </span>
            </div>
            <Sparkline data={history} />
            <div className="flex items-center justify-between text-[10px] font-mono text-muted-foreground tabular-nums">
                <span>{rec.count?.toLocaleString?.() ?? 0} samples</span>
                <span>{rec.lastTs ? fmtTime(rec.lastTs) : ""}</span>
            </div>
        </div>
    );
}

function Stat({ label, value, accent }) {
    return (
        <div className="flex flex-col">
            <span className="text-[9px] uppercase tracking-[0.15em] text-muted-foreground">{label}</span>
            <span className={`font-mono tabular-nums text-sm font-semibold ${accent ? "text-primary" : "text-foreground"}`}>{value}</span>
        </div>
    );
}

export default function ReceiverView({
    sinkStats,
    sinkTags,
    sinkHistory,
    sinkFrameLog,
    serial,
    onStart,
    onStop,
    runtimeActive,
    onStartSource,
}) {
    const termRef = useRef(null);
    const running = sinkStats.running;

    useEffect(() => {
        if (termRef.current) termRef.current.scrollTop = termRef.current.scrollHeight;
    }, [sinkFrameLog]);

    return (
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-4 items-start">
            {/* Dynamic received tags */}
            <section className="lg:col-span-8 rounded-md border border-border bg-card" data-testid="receiver-dashboard">
                <div className="flex items-center justify-between px-4 py-3 border-b border-border">
                    <div className="flex items-center gap-2">
                        <ArrowDownToLine className={`h-4 w-4 ${running ? "text-primary animate-livepulse" : "text-muted-foreground"}`} />
                        <h2 className="font-heading font-bold tracking-tight text-sm uppercase">Received Tags — Auto-Discovered</h2>
                    </div>
                    <span className="font-mono text-xs text-muted-foreground">{sinkTags.length} tags</span>
                </div>
                {sinkTags.length === 0 ? (
                    <div className="flex flex-col items-center justify-center py-24 text-center" data-testid="receiver-empty">
                        <Inbox className="h-10 w-10 text-muted-foreground/40 mb-3" />
                        <p className="text-sm text-muted-foreground">No data received yet.</p>
                        <p className="text-xs text-muted-foreground/70 mt-1">
                            Start the receiver, then run the source transmission. Tags appear here automatically as frames arrive.
                        </p>
                    </div>
                ) : (
                    <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3 p-3">
                        {sinkTags.map((rec) => (
                            <ReceivedTile key={rec.name} rec={rec} history={sinkHistory[rec.name]} />
                        ))}
                    </div>
                )}
            </section>

            {/* Control panel */}
            <section className="lg:col-span-4 rounded-md border border-border bg-card flex flex-col" data-testid="receiver-panel">
                <div className="flex items-center justify-between px-4 py-3 border-b border-border">
                    <div className="flex items-center gap-2">
                        <Inbox className="h-4 w-4 text-primary" />
                        <h2 className="font-heading font-bold tracking-tight text-sm uppercase">Ingest Receiver</h2>
                    </div>
                    <span className={`text-[10px] font-mono px-2 py-0.5 rounded ${running ? "bg-emerald-400/10 text-emerald-400" : "bg-secondary text-muted-foreground"}`}>
                        {running ? `● ${sinkStats.serial_port} @ ${sinkStats.baudrate}` : "○ OFFLINE"}
                    </span>
                </div>

                <div className="px-4 py-3 border-b border-border space-y-3">
                    <div className="space-y-2">
                        <SerialPortPicker prefix="receiver" label="Input Serial Port (from Sender)" placeholder="/dev/serial0" disabled={running} {...serial} />
                        <div className="flex items-center gap-2">
                            {running ? (
                                <button
                                    onClick={onStop}
                                    data-testid="stop-receiver-btn"
                                    className="flex-1 flex items-center justify-center gap-2 h-9 rounded-md bg-red-500/15 text-red-400 border border-red-500/30 hover:bg-red-500/25 transition-colors text-sm font-medium"
                                >
                                    <Square className="h-4 w-4" /> Stop Receiver
                                </button>
                            ) : (
                                <button
                                    onClick={onStart}
                                    data-testid="start-receiver-btn"
                                    className="flex-1 flex items-center justify-center gap-2 h-9 rounded-md bg-primary text-primary-foreground hover:bg-primary/90 transition-colors text-sm font-semibold"
                                >
                                    <Power className="h-4 w-4" /> Start Receiver
                                </button>
                            )}
                        </div>
                        <p className="text-[10px] text-muted-foreground font-mono">Only the serial port needs configuring — tags are learned from the stream and kept (dormant) when the Sender stops.</p>
                        {sinkStats.serial_error && <p className="text-[10px] font-mono text-red-400 break-all" data-testid="receiver-serial-error">{sinkStats.serial_error}</p>}
                    </div>

                    {running && (
                        <div className="rounded-md border border-primary/25 bg-primary/5 px-3 py-2">
                            <span className="text-[9px] uppercase tracking-[0.15em] text-muted-foreground">Re-published OPC UA Endpoint</span>
                            <p className="font-mono text-[11px] text-primary break-all mt-0.5">{sinkStats.opcua_endpoint}</p>
                            <p className="text-[10px] text-muted-foreground mt-0.5">External OPC UA clients can subscribe to the received tags here.</p>
                        </div>
                    )}

                    {running && !runtimeActive && (
                        <button
                            onClick={onStartSource}
                            data-testid="start-source-btn"
                            className="w-full flex items-center justify-center gap-2 h-9 rounded-md border border-primary/40 text-primary hover:bg-primary/10 transition-colors text-sm font-medium"
                        >
                            <PlugZap className="h-4 w-4" /> Start Source Transmission
                        </button>
                    )}

                    <div className="grid grid-cols-3 gap-2 pt-1">
                        <Stat label="Rate" value={fmtBytes(sinkStats.bps || 0) + "/s"} accent={running} />
                        <Stat label="Frames/s" value={sinkStats.fps || 0} accent={running} />
                        <Stat label="Frames RX" value={(sinkStats.frames_received || 0).toLocaleString()} />
                        <Stat label="RX Total" value={fmtBytes(sinkStats.bytes_received || 0)} />
                        <Stat label="Tags" value={sinkStats.tag_count || 0} accent={running} />
                        <Stat label="Uptime" value={`${sinkStats.uptime || 0}s`} />
                        <Stat label="Dormant" value={sinkStats.dormant_count || 0} />
                        <Stat label="CRC Errors" value={sinkStats.crc_errors || 0} />
                        <Stat label="Link" value={running ? (sinkStats.serial_connected ? "OK" : "LOST") : "—"} accent={running && sinkStats.serial_connected} />
                    </div>
                </div>

                <div className="flex items-center justify-between px-4 py-1.5 border-b border-border bg-black">
                    <span className="text-[9px] uppercase tracking-[0.2em] text-primary/70 font-mono">rx://serial-stream</span>
                    <span className="text-[9px] text-muted-foreground font-mono">seq #{sinkStats.last_seq || 0}</span>
                </div>
                <div ref={termRef} className="flex-1 min-h-[220px] max-h-[360px] overflow-y-auto scrollbar-thin bg-black scanlines p-3 font-mono text-[11px] leading-relaxed" data-testid="receiver-terminal">
                    {sinkFrameLog.length === 0 && <div className="text-muted-foreground/60">$ awaiting inbound frames…</div>}
                    {sinkFrameLog.map((f) => (
                        <div key={f.key} className="mb-1 break-all">
                            <span className="text-muted-foreground">[{fmtTime(f.ts)}]</span>{" "}
                            <span className="text-primary/80">#{String(f.seq).padStart(5, "0")}</span>{" "}
                            <span className={f.format === "json" ? "text-amber-400" : "text-fuchsia-400"}>{f.format === "json" ? "JSON" : f.format === "ctl" ? "CTL " : "BIN "}</span>{" "}
                            <span className="text-emerald-400">{f.byte_size}B</span>{" "}
                            <span className="text-muted-foreground">×{f.tag_count}</span>
                            {f.new_tags && f.new_tags.length > 0 && (
                                <span className="text-primary"> +NEW[{f.new_tags.join(",")}]</span>
                            )}
                            {f.revived && f.revived.length > 0 && <span className="text-emerald-300"> ↺REVIVED[{f.revived.join(",")}]</span>}
                            {f.dormant && <span className="text-amber-400"> ☾ {f.dormant.length} tag(s) dormant</span>}
                        </div>
                    ))}
                </div>
            </section>
        </div>
    );
}
