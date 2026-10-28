import { RefreshCw, Cable } from "lucide-react";

export default function SerialPortPicker({ prefix, label, port, setPort, baud, setBaud, ports, bauds, disabled, onRefresh, placeholder }) {
    return (
        <div className="space-y-1.5" data-testid={`${prefix}-serial-picker`}>
            <span className="text-[9px] uppercase tracking-[0.2em] text-muted-foreground flex items-center gap-1">
                <Cable className="h-3 w-3" /> {label}
            </span>
            <div className="flex items-center gap-2">
                <input
                    list={`${prefix}-port-list`}
                    value={port}
                    disabled={disabled}
                    placeholder={placeholder}
                    onChange={(e) => setPort(e.target.value)}
                    data-testid={`${prefix}-serial-port-input`}
                    className="h-9 flex-1 min-w-0 rounded-md border border-border bg-background px-3 font-mono text-xs disabled:opacity-50"
                />
                <datalist id={`${prefix}-port-list`}>
                    {ports.map((p) => (
                        <option key={p.device} value={p.device}>
                            {p.description}
                        </option>
                    ))}
                </datalist>
                <button
                    type="button"
                    onClick={onRefresh}
                    disabled={disabled}
                    title="Rescan serial ports"
                    data-testid={`${prefix}-serial-refresh-btn`}
                    className="h-9 w-9 shrink-0 flex items-center justify-center rounded-md border border-border text-muted-foreground hover:text-primary hover:border-primary/40 transition-colors disabled:opacity-50"
                >
                    <RefreshCw className="h-3.5 w-3.5" />
                </button>
            </div>
            <div className="flex items-center gap-2">
                <span className="text-[10px] font-mono text-muted-foreground w-12">BAUD</span>
                <select
                    value={baud}
                    disabled={disabled}
                    onChange={(e) => setBaud(Number(e.target.value))}
                    data-testid={`${prefix}-baud-select`}
                    className="h-8 flex-1 rounded-md border border-border bg-background px-2 font-mono text-xs tabular-nums disabled:opacity-50"
                >
                    {bauds.map((b) => (
                        <option key={b} value={b}>
                            {b.toLocaleString()} bps
                        </option>
                    ))}
                </select>
            </div>
            <p className="text-[10px] text-muted-foreground font-mono" data-testid={`${prefix}-detected-ports`}>
                {ports.length ? `Detected: ${ports.map((p) => p.device).join(", ")}` : "No ports detected — type a path, e.g. /dev/serial0 or COM3"}
            </p>
        </div>
    );
}
