import { AlertTriangle, Unplug, ShieldAlert } from "lucide-react";

const ICONS = { line_silent: Unplug, crc_errors: ShieldAlert, link_lost: Unplug };
const TITLES = { line_silent: "SERIAL LINE SILENT", crc_errors: "CHECKSUM ERRORS", link_lost: "SERIAL PORT LOST" };

export default function LinkAlarmBanner({ alarms }) {
    if (!alarms || alarms.length === 0) return null;
    return (
        <div className="space-y-2 mb-4" data-testid="link-alarm-banner">
            {alarms.map((a) => {
                const Icon = ICONS[a.code] || AlertTriangle;
                const critical = a.severity === "critical";
                return (
                    <div
                        key={a.code}
                        role="alert"
                        data-testid={`link-alarm-${a.code}`}
                        className={`flex items-center gap-3 rounded-md border px-4 py-3 animate-livepulse ${
                            critical ? "border-red-500/50 bg-red-500/10 text-red-300" : "border-amber-400/50 bg-amber-400/10 text-amber-300"
                        }`}
                    >
                        <Icon className="h-5 w-5 shrink-0" />
                        <div className="min-w-0">
                            <p className="font-heading font-bold text-xs tracking-[0.15em]">ALARM · {TITLES[a.code] || a.code}</p>
                            <p className="font-mono text-[11px] opacity-90 break-words">{a.message}</p>
                        </div>
                    </div>
                );
            })}
        </div>
    );
}
