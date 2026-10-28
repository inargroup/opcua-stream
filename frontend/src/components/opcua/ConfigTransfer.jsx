import { useRef, useState } from "react";
import { Download, Upload, FileJson } from "lucide-react";
import { toast } from "sonner";
import * as api from "@/lib/api";
import {
    AlertDialog,
    AlertDialogAction,
    AlertDialogCancel,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
} from "@/components/ui/alert-dialog";

const stamp = () => new Date().toISOString().slice(0, 16).replace(/[-:T]/g, "");

export default function ConfigTransfer({ busy, onImported }) {
    const fileRef = useRef(null);
    const [pending, setPending] = useState(null);
    const [working, setWorking] = useState(false);

    const download = async () => {
        try {
            const cfg = await api.exportConfig();
            const blob = new Blob([JSON.stringify(cfg, null, 2)], { type: "application/json" });
            const a = document.createElement("a");
            a.href = URL.createObjectURL(blob);
            a.download = `opcstream-config-${stamp()}.json`;
            a.click();
            URL.revokeObjectURL(a.href);
            toast.success(`Configuration downloaded · ${cfg.servers.length} servers, ${cfg.tags.length} tags`);
        } catch (e) {
            toast.error("Could not download configuration");
        }
    };

    const pick = async (e) => {
        const file = e.target.files?.[0];
        e.target.value = "";
        if (!file) return;
        try {
            const cfg = JSON.parse(await file.text());
            if (!Array.isArray(cfg.servers) || !Array.isArray(cfg.tags)) throw new Error();
            setPending({ name: file.name, cfg });
        } catch {
            toast.error("That file is not a valid OPC//STREAM configuration");
        }
    };

    const confirm = async () => {
        setWorking(true);
        try {
            const r = await api.importConfig(pending.cfg);
            toast.success(`Configuration loaded · ${r.servers} servers (${r.connected} connected), ${r.tags} tags`);
            if (r.password_needed.length) toast.warning(`Re-enter passwords for: ${r.password_needed.join(", ")}`, { duration: 10000 });
            await onImported(r.settings);
        } catch (e) {
            const d = e?.response?.data?.detail;
            toast.error(typeof d === "string" ? d : "Upload rejected — the file is invalid or damaged");
        } finally {
            setWorking(false);
            setPending(null);
        }
    };

    return (
        <div className="flex items-center justify-between rounded-md border border-border bg-card px-4 py-2 mb-4" data-testid="config-transfer">
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <FileJson className="h-4 w-4 text-primary" />
                <span className="font-heading font-bold uppercase tracking-tight text-foreground text-sm">Configuration File</span>
                <span className="hidden md:inline font-mono text-[10px]">servers · tags · serial settings — passwords are never saved</span>
            </div>
            <div className="flex items-center gap-2">
                <button onClick={download} data-testid="config-download-btn" className="flex items-center gap-1.5 h-8 px-3 rounded-md border border-border text-xs font-medium hover:border-primary/40 hover:text-primary transition-colors">
                    <Download className="h-3.5 w-3.5" /> Download
                </button>
                <button
                    onClick={() => (busy ? toast.error("Stop the transmission and the receiver before uploading") : fileRef.current?.click())}
                    data-testid="config-upload-btn"
                    className="flex items-center gap-1.5 h-8 px-3 rounded-md bg-primary text-primary-foreground text-xs font-semibold hover:bg-primary/90 transition-colors"
                >
                    <Upload className="h-3.5 w-3.5" /> Upload
                </button>
                <input ref={fileRef} type="file" accept=".json,application/json" className="hidden" onChange={pick} data-testid="config-file-input" />
            </div>

            <AlertDialog open={!!pending} onOpenChange={(o) => !o && !working && setPending(null)}>
                <AlertDialogContent data-testid="config-import-dialog">
                    <AlertDialogHeader>
                        <AlertDialogTitle>Replace the current configuration?</AlertDialogTitle>
                        <AlertDialogDescription>
                            {pending && (
                                <>
                                    <span className="font-mono">{pending.name}</span> contains {pending.cfg.servers.length} server(s) and {pending.cfg.tags.length} tag(s).
                                    All existing servers, tags and serial settings will be replaced. Servers with a username will need their password re-entered.
                                </>
                            )}
                        </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                        <AlertDialogCancel disabled={working} data-testid="config-import-cancel-btn">Cancel</AlertDialogCancel>
                        <AlertDialogAction
                            onClick={(e) => {
                                e.preventDefault();
                                confirm();
                            }}
                            disabled={working}
                            data-testid="config-import-confirm-btn"
                        >
                            {working ? "Loading…" : "Replace configuration"}
                        </AlertDialogAction>
                    </AlertDialogFooter>
                </AlertDialogContent>
            </AlertDialog>
        </div>
    );
}
