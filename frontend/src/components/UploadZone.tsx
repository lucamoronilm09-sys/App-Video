"use client";

import { useCallback, useRef, useState, DragEvent, ChangeEvent } from "react";
import { uploadMedia } from "@/lib/api";

interface UploadZoneProps {
  projectId: string;
  onUploadComplete: (mediaCount: number) => void;
  disabled?: boolean;
}

export function UploadZone({ projectId, onUploadComplete, disabled }: UploadZoneProps) {
  const [dragActive, setDragActive] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const uploadFiles = useCallback(async (files: File[]) => {
    setUploading(true);
    setProgress(0);
    setError(null);
    try {
      const data = await uploadMedia(projectId, files);
      setProgress(100);
      onUploadComplete(data.media.length);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Errore sconosciuto");
    } finally {
      setUploading(false);
      setTimeout(() => setProgress(0), 500);
    }
  }, [projectId, onUploadComplete]);

  const handleDrag = useCallback((e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    if (!disabled) setDragActive(e.type === "dragenter" || e.type === "dragover");
  }, [disabled]);

  const handleDrop = useCallback(async (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    if (disabled) return;
    const files = Array.from(e.dataTransfer.files);
    if (files.length) await uploadFiles(files);
  }, [disabled, uploadFiles]);

  const handleFileSelect = useCallback(async (e: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || []);
    if (files.length) await uploadFiles(files);
    e.target.value = "";
  }, [uploadFiles]);

  const accepted = "image/*,video/*";

  return (
    <div className="relative">
      <input
        ref={inputRef}
        type="file"
        multiple
        accept={accepted}
        onChange={handleFileSelect}
        className="hidden"
        disabled={disabled || uploading}
        id="file-upload"
      />
      <div
        onDragEnter={handleDrag}
        onDragLeave={handleDrag}
        onDragOver={handleDrag}
        onDrop={handleDrop}
        onClick={() => !disabled && !uploading && inputRef.current?.click()}
        className={`
          border-2 border-dashed rounded-xl p-8 text-center transition-colors
          ${dragActive ? "border-emerald-400 bg-emerald-900/20" : "border-slate-700 hover:border-slate-500"}
          ${disabled || uploading ? "opacity-50 cursor-not-allowed" : "cursor-pointer"}
        `}
        role="button"
        tabIndex={0}
        onKeyDown={e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); inputRef.current?.click(); }}}
      >
        {uploading ? (
          <div className="space-y-3">
            <div className="h-2 bg-slate-800 rounded-full overflow-hidden">
              <div
                className="h-full bg-emerald-400 transition-all duration-300"
                style={{ width: `${progress}%` }}
              />
            </div>
            <p className="text-sm text-slate-400">Caricamento in corso&hellip; {progress}%</p>
          </div>
        ) : error ? (
          <div className="text-rose-400">
            <p className="font-medium">Errore</p>
            <p className="text-sm">{error}</p>
            <button
              onClick={() => setError(null)}
              className="mt-2 text-xs underline hover:text-rose-300"
            >
              Riprova
            </button>
          </div>
        ) : (
          <div className="space-y-2">
            <svg
              className="mx-auto h-12 w-12 text-slate-500"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={1.5}
                d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"
              />
            </svg>
            <p className="text-slate-300">
              Trascina foto/video qui, o clicca per selezionare
            </p>
            <p className="text-xs text-slate-500">
              Formati: JPG, PNG, WebP, HEIC, MP4, MOV, MKV, WebM&hellip;
            </p>
          </div>
        )}
      </div>
    </div>
  );
}