// Pure decision logic for the render error boundary (code-review #9). The boundary itself MUST be a
// class — React exposes getDerivedStateFromError / componentDidCatch only on classes — and a class
// component carrying JSX can't be imported by `node --test` (Node strips types but not JSX). So the
// substantive logic lives here as plain, JSX-free functions the test drives directly; ErrorBoundary.tsx
// is thin glue over these. This is the same pure-seam split the app already uses elsewhere (status.ts
// under TopBar, prefs.ts under the theme/badge consumers): test the seam, not the JSX.

export interface BoundaryState {
  error: Error | null
}

// What getDerivedStateFromError returns: flip into the fallback. Whatever was thrown is normalized to
// an Error so the fallback can always read `.message` — React permits throwing non-Errors (a string,
// a null), and `String(x)` gives an honest one-liner for those.
export function deriveErrorState(error: unknown): BoundaryState {
  return { error: error instanceof Error ? error : new Error(String(error)) }
}

// The React `key` for the CONTENT boundary. Keying on the current route means a navigation — which
// changes `view` or `detailId`, and the sidebar/topbar survive a crashed screen so the user can still
// navigate — remounts the boundary with a fresh instance, auto-clearing a caught error. No manual
// reset wiring. Detail is keyed by its id, so switching between two Details (or closing one back to a
// list view) also resets; Detail's only local state is a transient "copied" flash, so the remount that
// causes is harmless.
export function contentBoundaryKey(view: string, detailId: string | null): string {
  return detailId ? `detail:${detailId}` : `view:${view}`
}

// The console.error arguments on catch, as a tuple the class spreads. This is the RENDERER process, so
// console.* — NOT the V3-16 engine /logs, which is the Python sidecar in a different process (the same
// process distinction #5 drew for its nav-block warning). The component stack is logged here for
// diagnosis but never shown in the UI.
export function formatBoundaryLog(
  error: unknown,
  componentStack: string | null | undefined,
): [string, unknown, string] {
  return ['[render] boundary caught', error, componentStack ?? '(no component stack)']
}
