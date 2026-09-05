"use client";

interface ErrorPanelProps {
  errors: { stage: string; message: string }[];
  onClear: () => Promise<void>;
  busy?: boolean;
}

/** M8: errori non bloccanti con pulizia esplicita dopo visione. */
export function ErrorPanel({ errors, onClear, busy }: ErrorPanelProps) {
  if (errors.length === 0) return null;
  return (
    <div className="rounded-lg border border-rose-800 bg-rose-900/30 p-4">
      <div className="mb-2 flex items-center justify-between">
        <h4 className="font-medium text-rose-300">
          Errori ({errors.length})
        </h4>
        <button
          type="button"
          disabled={busy}
          onClick={() => void onClear()}
          className="text-xs text-rose-300/80 hover:text-rose-200 hover:underline disabled:opacity-50"
        >
          Pulisci
        </button>
      </div>
      <ul className="max-h-40 space-y-1 overflow-y-auto text-sm text-rose-200">
        {errors.map((e, i) => (
          <li key={i}>
            <span className="text-rose-400">[{e.stage}]</span> {e.message}
          </li>
        ))}
      </ul>
    </div>
  );
}
