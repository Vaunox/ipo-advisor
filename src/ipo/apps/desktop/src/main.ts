import { app, BrowserWindow } from 'electron'
import { type ChildProcess } from 'node:child_process'
import path from 'node:path'
import { findRepoRoot, freePort, killEngine, spawnEngine, waitForHealth } from './sidecar'

const DEV = !app.isPackaged
let child: ChildProcess | null = null
let win: BrowserWindow | null = null
let engineReady = false

async function boot(): Promise<void> {
  const repoRoot = findRepoRoot(__dirname)
  const port = await freePort()
  const base = `http://127.0.0.1:${port}`
  console.log(`[boot] engine base ${base} (dev=${DEV})`)

  // Spawn the engine: dev runs the module from source; prod runs the bundled PyInstaller binary
  // shipped as an extraResource under resources/engine/.
  const enginePath = path.join(
    process.resourcesPath ?? '',
    'engine',
    process.platform === 'win32' ? 'ipo-engine.exe' : 'ipo-engine',
  )
  child = spawnEngine(port, { dev: DEV, repoRoot, enginePath })
  child.stdout?.on('data', (d) => console.log(`[engine] ${String(d).trim()}`))
  child.stderr?.on('data', (d) => console.error(`[engine] ${String(d).trim()}`))
  child.on('exit', (code) => {
    // If the engine dies mid-session, the renderer's /health poll flips to the engine-down state.
    console.error(`[engine] exited (code ${code})`)
  })

  win = new BrowserWindow({
    width: 1320,
    height: 860,
    minWidth: 1040,
    minHeight: 700,
    backgroundColor: '#0a0d12',
    title: 'IPO Advisor',
    autoHideMenuBar: true,
    show: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      additionalArguments: [`--engine-base=${base}`],
    },
  })
  win.once('ready-to-show', () => win?.show())

  // Show the splash (the readiness gate, made visible) while we wait — the dashboard is NOT loaded.
  await win.loadFile(path.join(__dirname, '..', 'splash.html'))

  const t0 = Date.now()
  engineReady = await waitForHealth(base, 30_000)
  console.log(`[boot] /health ${engineReady ? 'green' : 'TIMEOUT'} after ${Date.now() - t0}ms`)

  // Only now load the dashboard — a cold start never shows the UI before /health resolves. If it
  // timed out, the app still loads and its /health poll renders the engine-down state.
  if (DEV) {
    await win.loadURL('http://localhost:5173')
  } else {
    await win.loadFile(path.join(__dirname, '..', '..', 'pwa', 'dist', 'index.html'))
  }
}

app.whenReady().then(boot).catch((e) => console.error('[boot] failed', e))

// Clean teardown on every exit path — no orphaned python (the classic Electron+sidecar bug).
app.on('window-all-closed', () => {
  killEngine(child)
  app.quit()
})
app.on('before-quit', () => killEngine(child))
app.on('will-quit', () => killEngine(child))
process.on('exit', () => killEngine(child))
process.on('SIGINT', () => {
  killEngine(child)
  process.exit(0)
})
