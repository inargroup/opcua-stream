import { useEffect, useState } from "react";
import { Gauge, ArrowUpRight } from "lucide-react";
import { estimateLink } from "@/lib/api";

const STYLES = {
    ok: { bar: "bg-emerald-400", text: "text-emerald-400", label: "LINK OK" },
    tight: { bar: "bg-amber-400", text: "text-amber-400", label: "TIGHT" },
    overloaded: { bar: "bg-red-500", text: "text-red-400", label: "OVERLOADED" },
};

export default function SpeedAdvisor({ format, baud, setBaud, tagCount, disabled }) {
    const [est, setEst] = useState(null);

    useEffect(() => {
        let alive = true;
        estimateLink(format, baud)
            .then((d) => alive && setEst(d))
            .catch(() => {});
        return () => {
            alive = false;
        };
    }, [format, baud, tagCount]);

    if (!est) return null;
    const st = STYLES[est.status];
    return (
        <div className="rounded-md border border-border bg-background px-3 py-2 space-y-1.5" data-testid="speed-advisor" data-status={est.status}>
            <div className="flex items-center justify-between">
                <span className="text-[9px] uppercase tracking-[0.2em] text-muted-foreground flex items-center gap-1">
                    <Gauge className="h-3 w-3" /> Speed Advisor
                </span>
                <span className={`text-[10px] font-mono font-semibold ${st.text}`} data-testid="speed-advisor-status">
                    {st.label} · {est.load_percent}%
                </span>
            </div>
            <div className="h-1.5 w-full rounded bg-secondary overflow-hidden">
                <div className={`h-full ${st.bar} transition-[width] duration-500`} style={{ width: `${Math.min(est.load_percent, 100)}%` }} />
            </div>
            <p className="text-[10px] font-mono text-muted-foreground tabular-nums" data-testid="speed-advisor-detail">
                ~{Math.round(est.est_bytes_per_s).toLocaleString()} B/s needed of {Math.round(est.capacity_bytes_per_s).toLocaleString()} B/s · {est.tag_count} tags · {est.frames_per_s} frames/s
            </p>
            {est.suggested_baudrate && (
                <button
                    onClick={() => setBaud(est.suggested_baudrate)}
                    disabled={disabled}
                    data-testid="speed-advisor-apply-btn"
                    className={`w-full flex items-center justify-center gap-1.5 h-7 rounded border text-[11px] font-medium transition-colors disabled:opacity-50 ${
                        est.status === "overloaded" ? "border-red-500/40 text-red-300 hover:bg-red-500/10" : "border-amber-400/40 text-amber-300 hover:bg-amber-400/10"
                    }`}
                >
                    <ArrowUpRight className="h-3.5 w-3.5" /> Frames will drop — use {est.suggested_baudrate.toLocaleString()} bps
                </button>
            )}
            {est.status !== "ok" && !est.suggested_baudrate && (
                <p className="text-[10px] text-red-400 font-mono">Even the fastest baud cannot carry this load — slow sampling or remove tags.</p>
            )}
        </div>
    );
}
