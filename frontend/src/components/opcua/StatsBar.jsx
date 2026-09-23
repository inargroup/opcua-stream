import { Server as ServerIcon, Tag, Radio, Zap, Cpu, Settings2, Gauge, Inbox } from "lucide-react";

const fmtBytes = (b) => {
    if (b > 1048576) return `${(b / 1048576).toFixed(2)} MB`;
    if (b > 1024) return `${(b / 1024).toFixed(1)} KB`;
    return `${b | 0} B`;
};

function Metric({ label, value, sub, accent, testid }) {
    return (
        <div className="flex flex-col justify-center px-4 md:px-5 border-l border-border first:border-l-0" data-testid={testid}>
            <span className="text-[10px] uppercase tracking-[0.2em] text-muted-foreground">{label}</span>
            <span
                className={`font-mono tabular-nums text-lg md:text-xl font-semibold leading-tight ${accent ? "text-primary" : "text-foreground"}`}
            >
                {value}
            </span>
            {sub && <span className="text-[10px] text-muted-foreground font-mono">{sub}</span>}
        </div>
    );
}

export default function StatsBar({ mode, setMode, servers, tags, stats, wsConnected }) {
    const connected = servers.filter((s) => s.status?.connected).length;

    return (
        <header className="sticky top-0 z-30 border-b border-border bg-background/95 backdrop-blur mb-4">
            <div className="grid-texture">
                <div className="max-w-[1600px] mx-auto px-4 md:px-6">
                    {/* Row 1: brand + mode toggle */}
                    <div className="flex items-center justify-between py-3">
                        <div className="flex items-center gap-3">
                            <div className="h-9 w-9 rounded-md border border-primary/40 bg-primary/10 flex items-center justify-center">
                                <Cpu className="h-5 w-5 text-primary" />
                            </div>
                            <div>
                                <h1 className="font-heading font-800 tracking-tighter text-lg leading-none font-extrabold">
                                    OPC<span className="text-primary">//</span>STREAM
                                </h1>
                                <p className="text-[10px] uppercase tracking-[0.25em] text-muted-foreground mt-0.5">
                                    Multi-Server UA Client
                                </p>
                            </div>
                        </div>

                        <div className="flex items-center gap-4">
                            <div className="hidden md:flex items-center gap-2 text-xs font-mono">
                                <span
                                    className={`h-2 w-2 rounded-full ${wsConnected ? "bg-emerald-400 animate-livepulse" : "bg-red-500"}`}
                                />
                                <span className="text-muted-foreground">
                                    WS {wsConnected ? "LINKED" : "OFFLINE"}
                                </span>
                            </div>

                            <div className="flex items-center rounded-md border border-border bg-card p-0.5" data-testid="mode-toggle">
                                <button
                                    data-testid="mode-config-btn"
                                    onClick={() => setMode("config")}
                                    className={`flex items-center gap-1.5 px-3 md:px-4 py-1.5 rounded text-xs font-medium transition-colors duration-200 ${
                                        mode === "config"
                                            ? "bg-secondary text-foreground"
                                            : "text-muted-foreground hover:text-foreground"
                                    }`}
                                >
                                    <Settings2 className="h-3.5 w-3.5" /> Configuration
                                </button>
                                <button
                                    data-testid="mode-runtime-btn"
                                    onClick={() => setMode("runtime")}
                                    className={`flex items-center gap-1.5 px-3 md:px-4 py-1.5 rounded text-xs font-medium transition-colors duration-200 ${
                                        mode === "runtime"
                                            ? "bg-primary text-primary-foreground"
                                            : "text-muted-foreground hover:text-foreground"
                                    }`}
                                >
                                    <Radio className="h-3.5 w-3.5" /> Runtime
                                </button>
                                <button
                                    data-testid="mode-receiver-btn"
                                    onClick={() => setMode("receiver")}
                                    className={`flex items-center gap-1.5 px-3 md:px-4 py-1.5 rounded text-xs font-medium transition-colors duration-200 ${
                                        mode === "receiver"
                                            ? "bg-primary text-primary-foreground"
                                            : "text-muted-foreground hover:text-foreground"
                                    }`}
                                >
                                    <Inbox className="h-3.5 w-3.5" /> Receiver
                                </button>
                            </div>
                        </div>
                    </div>

                    {/* Row 2: KPIs */}
                    <div className="grid grid-cols-3 md:grid-cols-6 border-t border-border py-2.5">
                        <Metric testid="kpi-servers" label="Servers" value={`${connected}/${servers.length}`} sub="connected" />
                        <Metric testid="kpi-tags" label="Sampled Tags" value={tags.length} sub="configured" />
                        <Metric
                            testid="kpi-status"
                            label="Channel"
                            value={stats.active ? "LIVE" : "IDLE"}
                            sub={stats.format?.toUpperCase()}
                            accent={stats.active}
                        />
                        <Metric testid="kpi-frames" label="Frames TX" value={stats.frames_total?.toLocaleString?.() ?? 0} sub={`${stats.fps || 0} f/s`} />
                        <Metric testid="kpi-throughput" label="Data Rate" value={fmtBytes(stats.bps || 0) + "/s"} sub={fmtBytes(stats.bytes_total || 0) + " total"} accent={stats.active} />
                        <Metric testid="kpi-uptime" label="Uptime" value={`${stats.uptime || 0}s`} sub={`${stats.active_tag_count || 0} active`} />
                    </div>
                </div>
            </div>
        </header>
    );
}
