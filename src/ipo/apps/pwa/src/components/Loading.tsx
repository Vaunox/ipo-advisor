// Shared loading treatment — a subtle spinner + label, used by every screen's loading branch so
// the "is it working?" cue is consistent (replaces the old bare "Loading…" text). Respects
// prefers-reduced-motion via CSS (the ring stops spinning, stays a static dim ring).
export function Loading({ label }: { label: string }) {
  return (
    <div className="state" role="status" aria-live="polite">
      <div className="spinner" aria-hidden="true" />
      <p style={{ marginTop: 12 }}>{label}</p>
    </div>
  )
}
