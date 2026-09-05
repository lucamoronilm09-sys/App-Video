"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  driveAuthUrl,
  driveDisconnect,
  driveListFiles,
  driveStatus,
  isJobActive,
  saveDriveCredentials,
  type DriveEntry,
  type DriveStatus,
  type Job,
} from "@/lib/api";

interface DriveSectionProps {
  projectId: string;
  onSubmitImport: (fileIds: string[], folderIds: string[]) => Promise<Job>;
  job?: Job | null;
}

function isSupported(e: DriveEntry): boolean {
  if (e.is_folder) return true;
  if (e.mimeType === "image/svg+xml") return false;
  return e.mimeType.startsWith("image/") || e.mimeType.startsWith("video/");
}

/** M7 + coda: submit import in background, progress live dal job. */
export function DriveSection({ projectId, onSubmitImport, job }: DriveSectionProps) {
  const [status, setStatus] = useState<DriveStatus | null>(null);
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [folderId, setFolderId] = useState("root");
  const [stack, setStack] = useState<{ id: string; name: string }[]>([]);
  const [folderName, setFolderName] = useState("Il mio Drive");
  const [entries, setEntries] = useState<DriveEntry[]>([]);
  const [selectedFiles, setSelectedFiles] = useState<string[]>([]);
  const [selectedFolders, setSelectedFolders] = useState<{ id: string; name: string }[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const importing = submitting || isJobActive(job);

  const refreshStatus = useCallback(async () => {
    try {
      setStatus(await driveStatus());
    } catch {
      setStatus(null);
    }
  }, []);

  useEffect(() => {
    refreshStatus();
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [refreshStatus]);

  const loadFolder = useCallback(async (fid: string) => {
    setBusy(true);
    setError(null);
    try {
      const data = await driveListFiles(projectId, fid);
      setFolderId(data.current.id);
      setFolderName(data.current.name);
      setEntries(data.entries);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Lettura Drive fallita");
    } finally {
      setBusy(false);
    }
  }, [projectId]);

  useEffect(() => {
    if (status?.connected) void loadFolder("root");
  }, [status?.connected, loadFolder]);

  const stopPoll = () => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  };

  const handleSaveCredentials = async () => {
    setBusy(true);
    setError(null);
    try {
      await saveDriveCredentials(clientId, clientSecret);
      setClientSecret("");
      await refreshStatus();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Salvataggio fallito");
    } finally {
      setBusy(false);
    }
  };

  const handleConnect = async () => {
    setError(null);
    try {
      const url = await driveAuthUrl();
      window.open(url, "_blank", "width=520,height=640");
      stopPoll();
      let tries = 0;
      pollRef.current = setInterval(async () => {
        tries += 1;
        const s = await driveStatus().catch(() => null);
        if (s?.connected || tries > 90) {
          stopPoll();
          if (s) setStatus(s);
        }
      }, 2000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Connessione fallita");
    }
  };

  const handleDisconnect = async () => {
    await driveDisconnect().catch(() => null);
    setEntries([]);
    setSelectedFiles([]);
    setSelectedFolders([]);
    setStack([]);
    await refreshStatus();
  };

  const navigate = (id: string) => {
    setStack(prev => [...prev, { id: folderId, name: folderName }]);
    void loadFolder(id);
  };

  const goBack = () => {
    const prev = stack[stack.length - 1];
    if (!prev) return;
    setStack(s => s.slice(0, -1));
    void loadFolder(prev.id);
  };

  const toggleFile = (id: string) => {
    setSelectedFiles(prev => (prev.includes(id) ? prev.filter(f => f !== id) : [...prev, id]));
  };

  const toggleFolder = (id: string, name: string) => {
    setSelectedFolders(prev =>
      prev.some(f => f.id === id) ? prev.filter(f => f.id !== id) : [...prev, { id, name }],
    );
  };

  const handleImport = async () => {
    setSubmitting(true);
    setError(null);
    try {
      await onSubmitImport(selectedFiles, selectedFolders.map(f => f.id));
      setSelectedFiles([]);
      setSelectedFolders([]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Import fallito");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section aria-label="Import da Google Drive" className="rounded-xl border border-slate-700 bg-slate-900/50 p-4">
      <div className="mb-3 flex items-baseline justify-between">
        <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-400">
          Google Drive
        </h3>
        {status?.connected && status.email && (
          <span className="truncate text-xs text-slate-500">{status.email}</span>
        )}
      </div>

      {error && (
        <p className="mb-3 rounded-lg border border-rose-800 bg-rose-900/30 px-3 py-2 text-sm text-rose-200">
          {error}
        </p>
      )}

      {!status?.configured ? (
        <div className="space-y-2 text-sm">
          <p className="text-slate-400">
            Incolla le credenziali OAuth (Google Cloud Console → API e servizi → Credenziali →
            ID client OAuth tipo &ldquo;App web&rdquo;, con redirect{" "}
            <code className="text-xs text-slate-300">http://127.0.0.1:8000/api/drive/callback</code>{" "}
            e API Drive abilitata).
          </p>
          <input
            value={clientId}
            onChange={e => setClientId(e.target.value)}
            placeholder="Client ID"
            className="w-full rounded-lg border border-slate-700 bg-slate-800 px-2 py-1.5 text-sm text-slate-200"
          />
          <input
            value={clientSecret}
            onChange={e => setClientSecret(e.target.value)}
            placeholder="Client secret"
            type="password"
            className="w-full rounded-lg border border-slate-700 bg-slate-800 px-2 py-1.5 text-sm text-slate-200"
          />
          <button
            type="button"
            disabled={busy || !clientId.trim() || !clientSecret.trim()}
            onClick={handleSaveCredentials}
            className="rounded-lg bg-slate-700 px-3 py-1.5 text-sm text-white hover:bg-slate-600 disabled:opacity-50"
          >
            Salva credenziali
          </button>
        </div>
      ) : !status.connected ? (
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={handleConnect}
            className="rounded-lg bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-500"
          >
            Connetti Google Drive
          </button>
          <button
            type="button"
            onClick={() => { setClientId(""); setClientSecret(""); setStatus(s => (s ? { ...s, configured: false } : s)); }}
            className="text-xs text-slate-500 hover:text-slate-300"
          >
            cambia credenziali
          </button>
        </div>
      ) : (
        <div className="space-y-3">
          <div className="flex items-center justify-between gap-2">
            <div className="flex min-w-0 items-center gap-2 text-sm">
              {stack.length > 0 && (
                <button type="button" onClick={goBack} className="rounded px-1.5 py-0.5 text-slate-300 hover:bg-slate-700" aria-label="Cartella precedente">
                  ←
                </button>
              )}
              <span className="truncate font-medium text-slate-200">{busy ? "…" : folderName}</span>
            </div>
            <button type="button" onClick={handleDisconnect} className="shrink-0 text-xs text-slate-500 hover:text-slate-300">
              disconnetti
            </button>
          </div>

          <ul className="max-h-56 space-y-1 overflow-y-auto pr-1">
            {entries.map(e => {
              const supported = isSupported(e);
              const checked = e.is_folder
                ? selectedFolders.some(f => f.id === e.id)
                : selectedFiles.includes(e.id);
              return (
                <li
                  key={e.id}
                  className={`flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm ${supported ? "bg-slate-800/70" : "bg-slate-800/30 opacity-50"}`}
                  title={supported ? e.mimeType : `${e.mimeType} — non supportato`}
                >
                  <input
                    type="checkbox"
                    checked={checked}
                    disabled={!supported}
                    onChange={() => (e.is_folder ? toggleFolder(e.id, e.name) : toggleFile(e.id))}
                    aria-label={`Seleziona ${e.name}`}
                  />
                  {e.is_folder ? (
                    <button
                      type="button"
                      onClick={() => navigate(e.id)}
                      className="flex-1 truncate text-left text-sky-300 hover:underline"
                    >
                      📁 {e.name}
                    </button>
                  ) : (
                    <span className="flex-1 truncate text-slate-300">
                      {e.mimeType.startsWith("video/") ? "🎬" : "🖼️"} {e.name}
                    </span>
                  )}
                </li>
              );
            })}
            {entries.length === 0 && !busy && (
              <li className="py-4 text-center text-sm text-slate-500">Cartella vuota</li>
            )}
          </ul>

          <div className="flex items-center justify-between gap-2">
            <p className="text-xs text-slate-500">
              {selectedFiles.length} file · {selectedFolders.length} cartelle (ricorsive)
            </p>
            <button
              type="button"
              disabled={importing || (selectedFiles.length === 0 && selectedFolders.length === 0)}
              onClick={handleImport}
              className="rounded-lg bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-500 disabled:opacity-50"
            >
              {importing ? "Import in corso…" : "⬇ Importa nel progetto"}
            </button>
          </div>
          {importing && (
            <div className="space-y-1" aria-label="Avanzamento import">
              <div className="h-2 overflow-hidden rounded-full bg-slate-800">
                <div
                  className="h-full rounded-full bg-sky-500 transition-all duration-500"
                  style={{ width: `${Math.round((job && isJobActive(job) ? job.progress.fraction : 0) * 100)}%` }}
                />
              </div>
              <p className="text-xs text-slate-500">
                {job && isJobActive(job) && job.status === "running"
                  ? `Download da Drive… ${Math.round(job.progress.fraction * 100)}%${job.progress.note ? ` · ${job.progress.note}` : ""}`
                  : "Download in corso… i file appariranno in timeline da soli."}
              </p>
            </div>
          )}
          {job?.status === "failed" && (
            <p className="rounded-lg border border-rose-800 bg-rose-900/30 px-3 py-2 text-sm text-rose-200">
              Import fallito: {job.error ?? "errore sconosciuto"}
            </p>
          )}
        </div>
      )}
    </section>
  );
}
