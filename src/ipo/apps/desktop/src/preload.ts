import { contextBridge } from 'electron'

// The main process passes the engine's chosen base URL via --engine-base=<url> (the sidecar's free
// port). Expose it read-only so the renderer's API client targets the sidecar directly
// (see apps/pwa/src/api/client.ts, which reads window.__ENGINE_BASE__). No other bridge is exposed:
// the renderer has no Node access and nothing that could mutate the engine (advisory-only).
const arg = process.argv.find((a) => a.startsWith('--engine-base='))
const base = arg ? arg.slice('--engine-base='.length) : ''
contextBridge.exposeInMainWorld('__ENGINE_BASE__', base)
