import { LineChart, Line, YAxis, ResponsiveContainer } from "recharts";
import { Activity, Gauge } from "lucide-react";

function fmtValue(v) {
    if (v === null || v === undefined) return "—";
    if (typeof v === "boolean") return v ? "ON" : "OFF";
    if (typeof v === "number") return Number.isInteger(v) ? v.toLocaleString() : v.toFixed(2);
    return String(v);
}

function Sparkline({ data }) {
    if (!data || data.length < 2) {
        return <div className="h-10 w-full flex items-center text-[10px] text-muted-foreground/50 font-mono">awaiting samples…</div>;
    }
    return (
        <div className="h-10 w-full">
            <ResponsiveContainer width="100%" height="100%">
                <LineChart data={data} margin={{ top: 2, bottom: 2, left: 0, right: 0 }}>
                    <YAxis hide domain={["dataMin", "dataMax"]} />
                    <Line type="monotone" dataKey="v" stroke="#00E5FF" strokeWidth={1.5} dot={false} isAnimationActive={false} />
                </LineChart>
            </ResponsiveContainer>
        </div>
    );
}

function TagTile({ tag, sample, history }) {
    const good = sample?.quality === 192;
    const hasData = sample !== undefined;
    return (
        <div className="rounded-md border border-border bg-card p-4 flex flex-col gap-2 hover:border-primary/40 hover:-translate-y-[1px] transition-all duration-200" data-testid={`runtime-tile-${tag.id}`}>
            <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                    <p className="text-sm font-medium truncate">{tag.name}</p>
                    <p className="font-mono text-[10px] text-muted-foreground truncate">{tag.node_id}</p>
                </div>
                <span
                    className={`text-[9px] font-mono px-1.5 py-0.5 rounded shrink-0 ${
                        !hasData ? "bg-secondary text-muted-foreground" : good ? "bg-emerald-400/10 text-emerald-400" : "bg-red-500/10 text-red-400"
                    }`}
                >
                    {!hasData ? "IDLE" : good ? "GOOD" : "BAD"}
                </span>
            </div>
            <div className="flex items-end gap-1">
                <span className="font-mono tabular-nums text-2xl font-semibold text-primary leading-none" data-testid={`tile-value-${tag.id}`}>
                    {fmtValue(sample?.value)}
                </span>
                {tag.unit && <span className="text-[11px] text-muted-foreground font-mono mb-0.5">{tag.unit}</span>}
            </div>
            <Sparkline data={history} />
        </div>
    );
}

export default function RuntimeDashboard({ tags, tagValues, tagHistory, stats }) {
    if (tags.length === 0) {
        return (
            <div className="rounded-md border border-border bg-card h-full flex flex-col items-center justify-center py-24 text-center" data-testid="runtime-empty">
                <Gauge className="h-10 w-10 text-muted-foreground/40 mb-3" />
                <p className="text-sm text-muted-foreground">No tags configured.</p>
                <p className="text-xs text-muted-foreground/70 mt-1">Switch to Configuration mode to define source servers and tags.</p>
            </div>
        );
    }

    return (
        <section className="rounded-md border border-border bg-card" data-testid="runtime-dashboard">
            <div className="flex items-center justify-between px-4 py-3 border-b border-border">
                <div className="flex items-center gap-2">
                    <Activity className={`h-4 w-4 ${stats.active ? "text-primary animate-livepulse" : "text-muted-foreground"}`} />
                    <h2 className="font-heading font-bold tracking-tight text-sm uppercase">Live Process Values</h2>
                </div>
                <span className={`font-mono text-xs ${stats.active ? "text-primary" : "text-muted-foreground"}`}>
                    {stats.active ? "SAMPLING" : "PAUSED"}
                </span>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3 p-3">
                {tags.map((t) => (
                    <TagTile key={t.id} tag={t} sample={tagValues[t.id]} history={tagHistory[t.id]} />
                ))}
            </div>
        </section>
    );
}
