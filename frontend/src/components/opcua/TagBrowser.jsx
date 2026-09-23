import { useEffect, useState, useCallback } from "react";
import { Folder, ChevronRight, Variable, Plus, Check, Trash2, Home, Loader2, Tag as TagIcon, Server as ServerIcon } from "lucide-react";
import { toast } from "sonner";
import * as api from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from "@/components/ui/select";

export default function TagBrowser({ servers, tags, refreshTags }) {
    const connected = servers.filter((s) => s.status?.connected);
    const [serverId, setServerId] = useState("");
    const [path, setPath] = useState([]); // [{node_id, name}]
    const [nodes, setNodes] = useState([]);
    const [loading, setLoading] = useState(false);
    const [interval, setIntervalVal] = useState(200);

    useEffect(() => {
        if (!serverId && connected.length) setServerId(connected[0].id);
    }, [connected, serverId]);

    const load = useCallback(async (sid, nodeId) => {
        if (!sid) return;
        setLoading(true);
        try {
            const data = await api.browseServer(sid, nodeId);
            setNodes(data.nodes || []);
        } catch (e) {
            toast.error("Browse failed — is the server connected?");
            setNodes([]);
        } finally {
            setLoading(false);
        }
    }, []);

    useEffect(() => {
        if (serverId) {
            setPath([]);
            load(serverId, null);
        }
    }, [serverId, load]);

    const descend = (node) => {
        const newPath = [...path, { node_id: node.node_id, name: node.name }];
        setPath(newPath);
        load(serverId, node.node_id);
    };

    const gotoCrumb = (idx) => {
        if (idx < 0) {
            setPath([]);
            load(serverId, null);
        } else {
            const newPath = path.slice(0, idx + 1);
            setPath(newPath);
            load(serverId, newPath[newPath.length - 1].node_id);
        }
    };

    const isAdded = (node) => tags.some((t) => t.server_id === serverId && t.node_id === node.node_id);

    const addTag = async (node) => {
        try {
            await api.createTag({
                server_id: serverId,
                node_id: node.node_id,
                name: node.name,
                data_type: node.data_type || "Unknown",
                sampling_interval: Number(interval) || 200,
            });
            toast.success(`Tag "${node.name}" added`);
            refreshTags();
        } catch (e) {
            toast.error(e?.response?.data?.detail || "Failed to add tag");
        }
    };

    const removeTag = async (t) => {
        await api.deleteTag(t.id);
        refreshTags();
    };

    const serverTags = tags.filter((t) => t.server_id === serverId);
    const serverName = (id) => servers.find((s) => s.id === id)?.name || id;

    return (
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
            {/* Browser */}
            <section className="rounded-md border border-border bg-card flex flex-col" data-testid="tag-browser">
                <div className="flex items-center justify-between px-4 py-3 border-b border-border gap-2">
                    <div className="flex items-center gap-2 min-w-0">
                        <Variable className="h-4 w-4 text-primary" />
                        <h2 className="font-heading font-bold tracking-tight text-sm uppercase">Address Space</h2>
                    </div>
                    <Select value={serverId} onValueChange={setServerId}>
                        <SelectTrigger className="h-7 w-[160px] text-xs font-mono" data-testid="browse-server-select">
                            <SelectValue placeholder="Select server" />
                        </SelectTrigger>
                        <SelectContent>
                            {connected.length === 0 && <div className="px-2 py-2 text-xs text-muted-foreground">No connected servers</div>}
                            {connected.map((s) => (
                                <SelectItem key={s.id} value={s.id}>{s.name}</SelectItem>
                            ))}
                        </SelectContent>
                    </Select>
                </div>

                {/* breadcrumb */}
                <div className="flex items-center gap-1 px-4 py-2 border-b border-border text-xs font-mono overflow-x-auto scrollbar-thin">
                    <button className="text-muted-foreground hover:text-primary flex items-center gap-1" onClick={() => gotoCrumb(-1)} data-testid="breadcrumb-root">
                        <Home className="h-3 w-3" /> root
                    </button>
                    {path.map((p, i) => (
                        <span key={p.node_id} className="flex items-center gap-1">
                            <ChevronRight className="h-3 w-3 text-muted-foreground" />
                            <button className={i === path.length - 1 ? "text-primary" : "text-muted-foreground hover:text-primary"} onClick={() => gotoCrumb(i)}>
                                {p.name}
                            </button>
                        </span>
                    ))}
                </div>

                <div className="flex items-center gap-2 px-4 py-2 border-b border-border">
                    <span className="text-[10px] uppercase tracking-wider text-muted-foreground">Sample @</span>
                    <Input
                        type="number"
                        value={interval}
                        onChange={(e) => setIntervalVal(e.target.value)}
                        className="h-7 w-24 font-mono text-xs"
                        data-testid="sampling-interval-input"
                    />
                    <span className="text-[10px] text-muted-foreground font-mono">ms interval for new tags</span>
                </div>

                <div className="max-h-[420px] overflow-y-auto scrollbar-thin divide-y divide-border/60">
                    {loading && (
                        <div className="flex items-center justify-center py-10 text-muted-foreground text-sm gap-2">
                            <Loader2 className="h-4 w-4 animate-spin" /> Browsing…
                        </div>
                    )}
                    {!loading && !serverId && (
                        <div className="px-4 py-10 text-center text-sm text-muted-foreground">Connect and select a server to browse its nodes.</div>
                    )}
                    {!loading && serverId && nodes.length === 0 && (
                        <div className="px-4 py-10 text-center text-sm text-muted-foreground">No child nodes here.</div>
                    )}
                    {!loading &&
                        nodes.map((n) => (
                            <div key={n.node_id} className="px-4 py-2.5 flex items-center justify-between gap-3 hover:bg-secondary/40 transition-colors" data-testid={`browse-node-${n.name}`}>
                                {n.is_variable ? (
                                    <div className="min-w-0 flex-1">
                                        <div className="flex items-center gap-2">
                                            <Variable className="h-3.5 w-3.5 text-amber-400 shrink-0" />
                                            <span className="text-sm truncate">{n.name}</span>
                                            <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-secondary text-muted-foreground shrink-0">{n.data_type}</span>
                                        </div>
                                        <div className="flex items-center gap-2 mt-0.5 pl-5.5">
                                            <span className="font-mono text-[11px] text-muted-foreground truncate">{n.node_id}</span>
                                            <span className="font-mono text-[11px] text-primary tabular-nums">= {String(n.value)}</span>
                                        </div>
                                    </div>
                                ) : (
                                    <button className="min-w-0 flex-1 flex items-center gap-2 text-left" onClick={() => descend(n)}>
                                        <Folder className="h-3.5 w-3.5 text-primary shrink-0" />
                                        <span className="text-sm truncate">{n.name}</span>
                                        <ChevronRight className="h-3.5 w-3.5 text-muted-foreground ml-auto" />
                                    </button>
                                )}
                                {n.is_variable &&
                                    (isAdded(n) ? (
                                        <span className="flex items-center gap-1 text-xs text-emerald-400 shrink-0"><Check className="h-3.5 w-3.5" /> Added</span>
                                    ) : (
                                        <Button size="sm" variant="secondary" className="h-6 gap-1 shrink-0" onClick={() => addTag(n)} data-testid={`add-tag-${n.name}`}>
                                            <Plus className="h-3 w-3" /> Sample
                                        </Button>
                                    ))}
                            </div>
                        ))}
                </div>
            </section>

            {/* Configured tags */}
            <section className="rounded-md border border-border bg-card flex flex-col" data-testid="tag-list">
                <div className="flex items-center justify-between px-4 py-3 border-b border-border">
                    <div className="flex items-center gap-2">
                        <TagIcon className="h-4 w-4 text-primary" />
                        <h2 className="font-heading font-bold tracking-tight text-sm uppercase">Sampled Tags</h2>
                    </div>
                    <span className="font-mono text-xs text-muted-foreground">{serverTags.length} on {serverName(serverId) || "—"}</span>
                </div>
                <div className="max-h-[520px] overflow-y-auto scrollbar-thin divide-y divide-border/60">
                    {serverTags.length === 0 && (
                        <div className="px-4 py-10 text-center text-sm text-muted-foreground">No tags sampled yet. Add them from the address space.</div>
                    )}
                    {serverTags.map((t) => (
                        <div key={t.id} className="px-4 py-2.5 flex items-center justify-between gap-3 hover:bg-secondary/40 transition-colors" data-testid={`tag-row-${t.id}`}>
                            <div className="min-w-0">
                                <div className="flex items-center gap-2">
                                    <span className="h-1.5 w-1.5 rounded-full bg-amber-400" />
                                    <span className="text-sm truncate">{t.name}</span>
                                    {t.unit && <span className="text-[10px] text-muted-foreground font-mono">{t.unit}</span>}
                                </div>
                                <span className="font-mono text-[11px] text-muted-foreground truncate block">{t.node_id}</span>
                            </div>
                            <div className="flex items-center gap-2 shrink-0">
                                <div className="flex items-center gap-1">
                                    <Input
                                        type="number"
                                        defaultValue={t.sampling_interval}
                                        className="h-7 w-20 font-mono text-xs tabular-nums"
                                        onBlur={async (e) => {
                                            const v = Number(e.target.value);
                                            if (v && v !== t.sampling_interval) {
                                                await api.updateTag(t.id, { sampling_interval: v });
                                                refreshTags();
                                            }
                                        }}
                                        data-testid={`tag-interval-${t.id}`}
                                    />
                                    <span className="text-[10px] text-muted-foreground">ms</span>
                                </div>
                                <Button size="icon" variant="ghost" className="h-7 w-7 text-muted-foreground hover:text-red-400" onClick={() => removeTag(t)} data-testid={`delete-tag-${t.id}`}>
                                    <Trash2 className="h-3.5 w-3.5" />
                                </Button>
                            </div>
                        </div>
                    ))}
                </div>
            </section>
        </div>
    );
}
