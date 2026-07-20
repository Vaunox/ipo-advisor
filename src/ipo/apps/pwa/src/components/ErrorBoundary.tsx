// Render error boundary (code-review #9). Before this, main.tsx mounted the app with no boundary, so
// ANY uncaught render throw — a malformed field, an unexpected null, a bad shape from the engine —
// propagated to the root and React 18 unmounted the whole tree: a blank white screen, no recovery.
//
// THIS IS THE ONE CLASS COMPONENT in an otherwise all-hooks codebase, and deliberately so: React
// exposes the error-catching lifecycle (getDerivedStateFromError / componentDidCatch) ONLY on classes
// — there is no hook equivalent in React 18. The substantive logic (derive / key / log) lives in the
// pure, JSX-free errorboundary.ts so it can be unit-tested under `node --test`; this file is the thin
// React glue plus the two fallback UIs. Note: under <StrictMode> the dev build may log a caught error
// twice (double-invoked render); the packaged production build logs once.
//
// It complements — does not duplicate — the app's data-state handlers (EngineDown, the uncalibrated
// banner, refField's "unknown — data stale" / "not available"): those render on known-bad DATA; this
// catches a render EXCEPTION, which those never see.

import React from 'react'
import { IconAlert } from './Icons'
import {
  type BoundaryState,
  deriveErrorState,
  formatBoundaryLog,
} from './boundary'

interface Props {
  children: React.ReactNode
  // Given the caught error and a reset() that clears the boundary, return the fallback to render.
  fallback: (ctx: { error: Error; reset: () => void }) => React.ReactNode
}

class ErrorBoundary extends React.Component<Props, BoundaryState> {
  state: BoundaryState = { error: null }

  static getDerivedStateFromError(error: unknown): BoundaryState {
    return deriveErrorState(error)
  }

  componentDidCatch(error: unknown, info: React.ErrorInfo): void {
    // Renderer-process console — NOT the engine /logs (a different process). Stack goes here only.
    console.error(...formatBoundaryLog(error, info.componentStack))
  }

  private reset = (): void => this.setState({ error: null })

  render(): React.ReactNode {
    if (this.state.error) return this.props.fallback({ error: this.state.error, reset: this.reset })
    return this.props.children
  }
}

// --- Fallbacks (reuse the EngineDown visual language: .enginedown + .btn) -------------------------

// error.message shows as one muted mono line — honest, aids field diagnosis, carries no exposure (the
// app's own text). The component stack never appears here; it goes to console.error only.
function ContentErrorFallback({
  error,
  reset,
  onGoLive,
}: {
  error: Error
  reset: () => void
  onGoLive: () => void
}) {
  return (
    <div className="enginedown">
      <div className="ic">
        <IconAlert />
      </div>
      <h2>This screen hit an error</h2>
      <p>
        Something in this view failed to render. Your other screens are unaffected — retry, or move to
        another screen from the sidebar.
      </p>
      <p className="err-msg mono">{error.message}</p>
      <div className="err-actions">
        <button className="btn" onClick={reset}>
          Try again
        </button>
        <button className="btn ghost" onClick={onGoLive}>
          Go to Live
        </button>
      </div>
    </div>
  )
}

function RootErrorFallback({ error }: { error: Error }) {
  return (
    <div className="enginedown">
      <div className="ic">
        <IconAlert />
      </div>
      <h2>The app hit an unexpected error</h2>
      <p>Something failed to render at the top level. Reloading should recover it.</p>
      <p className="err-msg mono">{error.message}</p>
      <button className="btn" onClick={() => window.location.reload()}>
        Reload
      </button>
    </div>
  )
}

// The CONTENT boundary: scoped to the routed content region. A crashed screen shows a contained
// fallback while the sidebar/topbar/nav survive. Reset is automatic — the caller keys this on the
// route (see contentBoundaryKey), so navigating remounts it fresh; "Try again" re-mounts in place.
export function ContentErrorBoundary({
  children,
  onGoLive,
}: {
  children: React.ReactNode
  onGoLive: () => void
}) {
  return (
    <ErrorBoundary
      fallback={({ error, reset }) => (
        <ContentErrorFallback error={error} reset={reset} onGoLive={onGoLive} />
      )}
    >
      {children}
    </ErrorBoundary>
  )
}

// The ROOT boundary: last-resort catch-all around the whole app, for a throw in the shell itself
// (sidebar, topbar, App's own body) that sits ABOVE the content boundary. Nav is dead if the shell
// threw, so the only recovery offered is a full reload.
export function RootErrorBoundary({ children }: { children: React.ReactNode }) {
  return (
    <ErrorBoundary fallback={({ error }) => <RootErrorFallback error={error} />}>
      {children}
    </ErrorBoundary>
  )
}
