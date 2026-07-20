import { contextBridge, ipcRenderer } from 'electron'
import type { SeenState, UiPrefs } from './settings'

// The main process passes the engine's chosen base URL via --engine-base=<url> (the sidecar's free
// port). Expose it read-only so the renderer's API client targets the sidecar directly
// (see apps/pwa/src/api/client.ts, which reads window.__ENGINE_BASE__).
const arg = process.argv.find((a) => a.startsWith('--engine-base='))
const base = arg ? arg.slice('--engine-base='.length) : ''
contextBridge.exposeInMainWorld('__ENGINE_BASE__', base)

// A minimal, advisory-only control surface for the desktop shell. Nothing here can mutate a
// verdict or place an order (Inviolable Rule 6) — it toggles OS integration (startup/tray) and
// restarts the local sidecar. Each call round-trips to a main-process ipcMain handler.
interface StartupPrefs {
  launchOnStartup: boolean
  minimizeToTray: boolean
  startMinimized: boolean
}

contextBridge.exposeInMainWorld('ipoDesktop', {
  getStartupSettings: (): Promise<StartupPrefs> => ipcRenderer.invoke('startup:get'),
  setStartupSettings: (prefs: StartupPrefs): Promise<void> =>
    ipcRenderer.invoke('startup:set', prefs),
  // Durable UI-prefs store (the app config file). getPrefs resolves null until first persisted.
  getPrefs: (): Promise<UiPrefs | null> => ipcRenderer.invoke('prefs:get'),
  setPrefs: (ui: UiPrefs): Promise<void> => ipcRenderer.invoke('prefs:set', ui),
  // OP-3: the notification seen-sets, a SEPARATE durable store (seen-state.json) so the high-frequency
  // seen writes never rewrite the low-frequency config file. getSeen resolves null until first persisted.
  getSeen: (): Promise<SeenState | null> => ipcRenderer.invoke('seen:get'),
  setSeen: (seen: SeenState): Promise<void> => ipcRenderer.invoke('seen:set', seen),
  restartEngine: (): Promise<boolean> => ipcRenderer.invoke('engine:restart'),
  // Ask the engine for a real NSE pull (v3 BUG 1 / Defect 1). The renderer stays read-only: this is
  // a request routed through the trusted shell, not a mutating call to the engine's GET-only API.
  refresh: (): Promise<boolean> => ipcRenderer.invoke('engine:refresh'),
  // Open a URL in the user's real browser (v3 V3-6, Allotment deep-link + RHP). The main process
  // validates it against `kind`'s rule before opening (a pinned host for 'registrar', any https for
  // 'rhp'); nothing is navigated inside the app (no in-app webview).
  openExternal: (url: string, kind: 'registrar' | 'rhp'): Promise<boolean> =>
    ipcRenderer.invoke('shell:openExternal', url, kind),
})
