// Read-only fetch wrapper over the advisory engine's GET API.
//
// Base resolution: the Electron shell injects `window.__ENGINE_BASE__ = http://127.0.0.1:<port>`
// (the sidecar's free port); in the browser dev server it falls back to `/api`, which Vite
// proxies to the local engine. There are deliberately no POST/PUT/DELETE helpers — the app is
// advisory and cannot mutate anything (Invariant 4).

declare global {
  interface Window {
    __ENGINE_BASE__?: string
  }
}

export const engineBase = (): string => window.__ENGINE_BASE__ ?? '/api'

export async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(`${engineBase()}${path}`, { headers: { accept: 'application/json' } })
  if (!res.ok) {
    throw new Error(`engine ${res.status} ${res.statusText} for ${path}`)
  }
  return (await res.json()) as T
}
