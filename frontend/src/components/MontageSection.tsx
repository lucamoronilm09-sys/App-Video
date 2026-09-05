"use client";

import { useState } from "react";
import type { ProjectState } from "@/lib/api";

interface MontageSectionProps {
  project: ProjectState;
  onGenerate: () => Promise<void>;
  busy?: boolean;
}

const MOVEMENT_LABEL: Record<string, string> = {
  pan_left: "Pan ←",
  pan_right: "Pan →",
  zoom_in_slow: "Zoom +",
  zoom_out_slow: "Zoom −",
  pan_and_zoom_diag: "Diag",
};

/** M4: genera il piano di montaggio e ne mostra l'anteprima (EDL + totale). */
export function MontageSection({ project, onGenerate, busy }: MontageSectionProps) {
  const [error, setError] = useState<string | null>(null);
  const edl = project.edit_decision_list ?? [];
  const manifest = project.render_manifest;

  const handleClick = async () => {
    setError(null);
    try {
      await onGenerate();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Generazione montaggio fallita");
    }
  };

  return (
    <section aria-label="Piano di montaggio" className="rounded-xl border border-slate-700 bg-slate-900/50 p-4">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-400">
          Montaggio
        </h3>
        <button
          type="button"
          disabled={busy || project.media.length === 0}
          onClick={handleClick}
          className="rounded-lg bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-emerald-500 disabled:opacity-50"
        >
          {busy ? "Generazione…" : edl.length ? "↻ Rigenera montaggio" : "✨ Genera montaggio"}
        </button>
      </div>

      {error && (
        <p className="mb-3 rounded-lg border border-rose-800 bg-rose-900/30 px-3 py-2 text-sm text-rose-200">
          {error}
        </p>
      )}

      {edl.length === 0 && !error && (
        <p className="text-sm text-slate-500">
          Il regista IA deciderà Ken Burns, dissolvenze e sincronizzazione sulla musica.
        </p>
      )}

      {edl.length > 0 && (
        <div className="space-y-3">
          <p className="text-sm text-slate-300">
            {edl.length} clip · totale{" "}
            <strong>{manifest ? manifest.total_sec.toFixed(1) : "…"}s</strong>
            {manifest?.audio ? " · con audio" : " · senza audio"}
          </p>
          <ol className="space-y-1 text-xs text-slate-300">
            {edl.map((e, i) => (
              <li
                key={e.media_id}
                className="flex items-center justify-between gap-2 rounded-lg bg-slate-800/70 px-2.5 py-1.5"
              >
                <span className="font-bold text-slate-400">#{i + 1}</span>
                <span className="tabular-nums">⏱ {e.start_sec_in_final_video.toFixed(1)}s</span>
                <span className="tabular-nums">{e.duration_sec.toFixed(1)}s</span>
                <span className="flex-1 truncate text-right text-slate-400">
                  {e.ken_burns ? (MOVEMENT_LABEL[e.ken_burns.movement] ?? e.ken_burns.movement) : "▶ video"}
                </span>
                {e.transition_out > 0 && (
                  <span className="text-slate-500" title="Dissolvenza incrociata verso la clip successiva">
                    ⋈ {e.transition_out.toFixed(1)}s
                  </span>
                )}
              </li>
            ))}
          </ol>
        </div>
      )}
    </section>
  );
}
