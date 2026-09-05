"use client";

import type { BackgroundFill } from "@/lib/api";

export interface OutputSpec {
  resolution: string;
  fps: number;
  background_fill: BackgroundFill;
  vcodec: "h264" | "h265";
}

interface ProjectSettingsProps {
  spec: OutputSpec;
  onSave: (patch: { background_fill?: BackgroundFill; resolution?: string; fps?: number; vcodec?: "h264" | "h265" }) => Promise<void>;
  busy?: boolean;
}

const RESOLUTIONS = ["1280x720", "1920x1080", "3840x2160"];
const FPS_OPTIONS = [23, 24, 25, 29, 30, 50, 59, 60];

/** Pannello M2: sfondo default per i verticali + risoluzione/fps di output. */
export function ProjectSettings({ spec, onSave, busy }: ProjectSettingsProps) {
  return (
    <section aria-label="Impostazioni output" className="rounded-xl border border-slate-700 bg-slate-900/50 p-4">
      <h3 className="mb-3 text-sm font-semibold uppercase tracking-wider text-slate-400">
        Output 16:9
      </h3>
      <div className="flex flex-wrap items-end gap-4">
        <label className="flex flex-col gap-1 text-xs text-slate-400">
          Sfondo verticali
          <select
            value={spec.background_fill}
            disabled={busy}
            onChange={e => void onSave({ background_fill: e.target.value as BackgroundFill })}
            className="rounded-lg border border-slate-700 bg-slate-800 px-2 py-1.5 text-sm text-slate-200 disabled:opacity-50"
            title="Riempimento laterale per i media verticali (mai croppati)"
          >
            <option value="blur">Blur</option>
            <option value="solid_color">Tinta unita</option>
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-slate-400">
          Risoluzione
          <select
            value={RESOLUTIONS.includes(spec.resolution) ? spec.resolution : "1920x1080"}
            disabled={busy}
            onChange={e => void onSave({ resolution: e.target.value })}
            className="rounded-lg border border-slate-700 bg-slate-800 px-2 py-1.5 text-sm text-slate-200 disabled:opacity-50"
          >
            {RESOLUTIONS.map(r => (
              <option key={r} value={r}>{r}</option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-slate-400">
          FPS
          <select
            value={FPS_OPTIONS.includes(spec.fps) ? spec.fps : 30}
            disabled={busy}
            onChange={e => void onSave({ fps: Number(e.target.value) })}
            className="rounded-lg border border-slate-700 bg-slate-800 px-2 py-1.5 text-sm text-slate-200 disabled:opacity-50"
          >
            {FPS_OPTIONS.map(f => (
              <option key={f} value={f}>{f}</option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-slate-400">
          Codec
          <select
            value={spec.vcodec ?? "h264"}
            disabled={busy}
            onChange={e => void onSave({ vcodec: e.target.value as "h264" | "h265" })}
            className="rounded-lg border border-slate-700 bg-slate-800 px-2 py-1.5 text-sm text-slate-200 disabled:opacity-50"
            title="H.264 compatibile ovunque, H.265 file più leggeri"
          >
            <option value="h264">H.264</option>
            <option value="h265">H.265</option>
          </select>
        </label>
        {busy && <span className="pb-2 text-xs text-slate-500">Salvataggio…</span>}
      </div>
      <p className="mt-2 text-[11px] text-slate-500">
        I verticali restano sempre interi e centrati; lo sfondo riempie solo i lati.
      </p>
    </section>
  );
}
