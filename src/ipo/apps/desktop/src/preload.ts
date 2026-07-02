import { contextBridge, ipcRenderer } from 'electron'

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
  restartEngine: (): Promise<boolean> => ipcRenderer.invoke('engine:restart'),
})
