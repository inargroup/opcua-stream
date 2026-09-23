import { useState } from "react";
import { Plus, Trash2, Plug, PlugZap, Loader2, Server as ServerIcon, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import * as api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
    DialogTrigger,
    DialogFooter,
} from "@/components/ui/dialog";
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from "@/components/ui/select";

const empty = { name: "", endpoint: "opc.tcp://", security_policy: "None", username: "", password: "" };

export default function ServerManager({ servers, refreshServers, refreshTags }) {
    const [open, setOpen] = useState(false);
    const [form, setForm] = useState(empty);
    const [busy, setBusy] = useState({});

    const setField = (k, v) => setForm((f) => ({ ...f, [k]: v }));

    const submit = async () => {
        if (!form.name.trim() || !form.endpoint.trim()) {
            toast.error("Name and endpoint are required");
            return;
        }
        try {
            await api.createServer({
                name: form.name.trim(),
                endpoint: form.endpoint.trim(),
                security_policy: form.security_policy,
                username: form.username || null,
                password: form.password || null,
            });
            toast.success("Server added");
            setForm(empty);
            setOpen(false);
            refreshServers();
        } catch (e) {
            toast.error("Failed to add server");
        }
    };

    const toggleConnect = async (s) => {
        setBusy((b) => ({ ...b, [s.id]: true }));
        try {
            if (s.status?.connected) {
                await api.disconnectServer(s.id);
                toast("Disconnected " + s.name);
            } else {
                await api.connectServer(s.id);
                toast.success("Connected " + s.name);
            }
            await refreshServers();
        } catch (e) {
            toast.error(e?.response?.data?.detail || "Connection error");
            await refreshServers();
        } finally {
            setBusy((b) => ({ ...b, [s.id]: false }));
        }
    };

    const remove = async (s) => {
        await api.deleteServer(s.id);
        toast("Removed " + s.name);
        refreshServers();
        refreshTags();
    };

    return (
        <section className="rounded-md border border-border bg-card" data-testid="server-manager">
            <div className="flex items-center justify-between px-4 py-3 border-b border-border">
                <div className="flex items-center gap-2">
                    <ServerIcon className="h-4 w-4 text-primary" />
                    <h2 className="font-heading font-bold tracking-tight text-sm uppercase">Source Servers</h2>
                </div>
                <div className="flex items-center gap-1">
                    <Button variant="ghost" size="icon" className="h-7 w-7" onClick={refreshServers} data-testid="refresh-servers-btn">
                        <RefreshCw className="h-3.5 w-3.5" />
                    </Button>
                    <Dialog open={open} onOpenChange={setOpen}>
                        <DialogTrigger asChild>
                            <Button size="sm" className="h-7 gap-1 bg-primary text-primary-foreground hover:bg-primary/90" data-testid="add-server-button">
                                <Plus className="h-3.5 w-3.5" /> Add
                            </Button>
                        </DialogTrigger>
                        <DialogContent className="bg-card border-border">
                            <DialogHeader>
                                <DialogTitle className="font-heading tracking-tight">Add OPC UA Server</DialogTitle>
                            </DialogHeader>
                            <div className="space-y-3">
                                <div>
                                    <Label className="text-xs">Name</Label>
                                    <Input data-testid="server-name-input" value={form.name} onChange={(e) => setField("name", e.target.value)} placeholder="Line 1 PLC" className="mt-1 font-mono" />
                                </div>
                                <div>
                                    <Label className="text-xs">Endpoint URL</Label>
                                    <Input data-testid="server-endpoint-input" value={form.endpoint} onChange={(e) => setField("endpoint", e.target.value)} placeholder="opc.tcp://host:4840" className="mt-1 font-mono" />
                                </div>
                                <div>
                                    <Label className="text-xs">Security Policy</Label>
                                    <Select value={form.security_policy} onValueChange={(v) => setField("security_policy", v)}>
                                        <SelectTrigger className="mt-1 font-mono" data-testid="server-security-select">
                                            <SelectValue />
                                        </SelectTrigger>
                                        <SelectContent>
                                            <SelectItem value="None">None (Anonymous)</SelectItem>
                                            <SelectItem value="Basic256Sha256">Basic256Sha256</SelectItem>
                                        </SelectContent>
                                    </Select>
                                </div>
                                <div className="grid grid-cols-2 gap-3">
                                    <div>
                                        <Label className="text-xs">Username (opt.)</Label>
                                        <Input data-testid="server-username-input" value={form.username} onChange={(e) => setField("username", e.target.value)} className="mt-1 font-mono" />
                                    </div>
                                    <div>
                                        <Label className="text-xs">Password (opt.)</Label>
                                        <Input data-testid="server-password-input" type="password" value={form.password} onChange={(e) => setField("password", e.target.value)} className="mt-1 font-mono" />
                                    </div>
                                </div>
                            </div>
                            <DialogFooter>
                                <Button onClick={submit} className="bg-primary text-primary-foreground hover:bg-primary/90" data-testid="save-server-button">
                                    Save Server
                                </Button>
                            </DialogFooter>
                        </DialogContent>
                    </Dialog>
                </div>
            </div>

            <div className="divide-y divide-border">
                {servers.length === 0 && (
                    <div className="px-4 py-10 text-center text-sm text-muted-foreground">No servers defined.</div>
                )}
                {servers.map((s) => {
                    const on = s.status?.connected;
                    return (
                        <div key={s.id} className="px-4 py-3 flex items-start justify-between gap-3 hover:bg-secondary/40 transition-colors" data-testid={`server-item-${s.id}`}>
                            <div className="min-w-0">
                                <div className="flex items-center gap-2">
                                    <span className={`h-2 w-2 rounded-full shrink-0 ${on ? "bg-emerald-400 animate-livepulse" : "bg-red-500"}`} />
                                    <span className="font-medium text-sm truncate">{s.name}</span>
                                </div>
                                <p className="font-mono text-[11px] text-muted-foreground truncate mt-0.5">{s.endpoint}</p>
                                <div className="flex items-center gap-3 mt-1 text-[10px] uppercase tracking-wider text-muted-foreground">
                                    <span>{s.security_policy}</span>
                                    <span>·</span>
                                    <span className="text-primary/80">{s.tag_count} tags</span>
                                    {s.status?.error && <span className="text-red-400 normal-case tracking-normal truncate max-w-[140px]">{s.status.error}</span>}
                                </div>
                            </div>
                            <div className="flex items-center gap-1 shrink-0">
                                <Button
                                    size="sm"
                                    variant={on ? "secondary" : "default"}
                                    className={`h-7 gap-1 ${on ? "" : "bg-primary text-primary-foreground hover:bg-primary/90"}`}
                                    disabled={busy[s.id]}
                                    onClick={() => toggleConnect(s)}
                                    data-testid={`toggle-connect-${s.id}`}
                                >
                                    {busy[s.id] ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : on ? <PlugZap className="h-3.5 w-3.5" /> : <Plug className="h-3.5 w-3.5" />}
                                    {on ? "Disc." : "Conn."}
                                </Button>
                                <Button size="icon" variant="ghost" className="h-7 w-7 text-muted-foreground hover:text-red-400" onClick={() => remove(s)} data-testid={`delete-server-${s.id}`}>
                                    <Trash2 className="h-3.5 w-3.5" />
                                </Button>
                            </div>
                        </div>
                    );
                })}
            </div>
        </section>
    );
}
