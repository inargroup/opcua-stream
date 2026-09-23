import { useEffect, useRef } from "react";
import { Play, Square, Braces, Binary, Radio } from "lucide-react";

const fmtBytes = (b) => {
    if (b > 1048576) return `${(b / 1048576).toFixed(2)} MB`;
    if (b > 1024) return `${(b / 1024).toFixed(1)} KB`;
    return `${b | 0} B`;
};

const fmtTime = (iso) => {
    try {
        const d = new Date(iso);
        return d.toLocaleTimeString("en-GB", { hour12: false }) + "." + String(d.getMilliseconds()).padStart(3, "0");
    } catch {
        return "";
    }
};

function Stat({ label, value, accent }) {
    return (
        <div className="flex flex-col">
            <span className="text-[9px] uppercase tracking-[0.15em] text-muted-foreground">{label}</span>
            <span className={`font-mono tabular-nums text-sm font-semibold ${accent ? "text-primary" : "text-foreground"}`}>{value}</span>
        </div>
    );
}

export default function SerialMonitor({ stats, format, onStart, onStop, onFormat, frameLog }) {
    const termRef = useRef(null);

    useEffect(() => {
        if (termRef.current) termRef.current.scrollTop = termRef.current.scrollHeight;
    }, [frameLog]);

    return (
        <section className="rounded-md border border-border bg-card flex flex-col h-full" data-testid="serial-monitor">
            <div className="flex items-center justify-between px-4 py-3 border-b border-border">
                <div className="flex items-center gap-2">
                    <Radio className={`h-4 w-4 ${stats.active ? "text-primary animate-livepulse" : "text-muted-foreground"}`} />
                    <h2 className="font-heading font-bold tracking-tight text-sm uppercase">Serial Channel</h2>
                </div>
                <span className={`text-[10px] font-mono px-2 py-0.5 rounded ${stats.active ? "bg-primary/10 text-primary" : "bg-secondary text-muted-foreground"}`}>
                    {stats.active ? "● TRANSMITTING" : "○ STOPPED"}
                </span>
            </div>

            {/* Controls */}
            <div className="px-4 py-3 border-b border-border space-y-3">
                <div>
                    <span className="text-[9px] uppercase tracking-[0.2em] text-muted-foreground">Serialization Format</span>
                    <div className="flex items-center rounded-md border border-border bg-background p-0.5 mt-1" data-testid="format-toggle">
                        <button
                            data-testid="format-json-btn"
                            onClick={() => onFormat("json")}
                            className={`flex-1 flex items-center justify-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium transition-colors ${
                                format === "json" ? "bg-secondary text-foreground" : "text-muted-foreground hover:text-foreground"
                            }`}
                        >
                            <Braces className="h-3.5 w-3.5" /> JSON
                        </button>
                        <button
                            data-testid="format-msgpack-btn"
                            onClick={() => onFormat("msgpack")}
                            className={`flex-1 flex items-center justify-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium transition-colors ${
                                format === "msgpack" ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"
                            }`}
                        >
                            <Binary className="h-3.5 w-3.5" /> Binary
                        </button>
                    </div>
                </div>

                {stats.active ? (
                    <button
                        onClick={onStop}
                        data-testid="stop-transmission-btn"
                        className="w-full flex items-center justify-center gap-2 py-2 rounded-md bg-red-500/15 text-red-400 border border-red-500/30 hover:bg-red-500/25 transition-colors text-sm font-medium"
                    >
                        <Square className="h-4 w-4" /> Stop Transmission
                    </button>
                ) : (
                    <button
                        onClick={onStart}
                        data-testid="start-transmission-btn"
                        className="w-full flex items-center justify-center gap-2 py-2 rounded-md bg-primary text-primary-foreground hover:bg-primary/90 transition-colors text-sm font-semibold"
                    >
                        <Play className="h-4 w-4" /> Start Transmission
                    </button>
                )}

                <div className="grid grid-cols-3 gap-2 pt-1">
                    <Stat label="Rate" value={fmtBytes(stats.bps || 0) + "/s"} accent={stats.active} />
                    <Stat label="Frames/s" value={stats.fps || 0} accent={stats.active} />
                    <Stat label="Frames" value={(stats.frames_total || 0).toLocaleString()} />
                    <Stat label="TX Total" value={fmtBytes(stats.bytes_total || 0)} />
                    <Stat label="Uptime" value={`${stats.uptime || 0}s`} />
                    <Stat label="Tags" value={stats.active_tag_count || 0} />
                </div>
            </div>

            {/* Terminal */}
            <div className="flex items-center justify-between px-4 py-1.5 border-b border-border bg-black">
                <span className="text-[9px] uppercase tracking-[0.2em] text-primary/70 font-mono">tx://frame-stream</span>
                <span className="text-[9px] text-muted-foreground font-mono">{frameLog.length} frames buffered</span>
            </div>
            <div ref={termRef} className="flex-1 min-h-[260px] max-h-[420px] overflow-y-auto scrollbar-thin bg-black scanlines p-3 font-mono text-[11px] leading-relaxed" data-testid="serial-terminal">
                {frameLog.length === 0 && (
                    <div className="text-muted-foreground/60">$ waiting for transmission stream…</div>
                )}
                {frameLog.map((f) => (
                    <div key={f.seq} className="mb-1 break-all">
                        <span className="text-muted-foreground">[{fmtTime(f.ts)}]</span>{" "}
                        <span className="text-primary/80">#{String(f.seq).padStart(5, "0")}</span>{" "}
                        <span className={f.format === "json" ? "text-amber-400" : "text-fuchsia-400"}>{f.format === "json" ? "JSON" : "BIN "}</span>{" "}
                        <span className="text-emerald-400">{f.byte_size}B</span>{" "}
                        <span className="text-muted-foreground">×{f.tag_count}</span>
                        <span className="text-primary/90"> ▶ </span>
                        <span className="text-cyan-200/80">{f.preview}</span>
                    </div>
                ))}
            </div>
        </section>
    );
}
