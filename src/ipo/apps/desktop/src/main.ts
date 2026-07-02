import { app, BrowserWindow } from 'electron'
import { type ChildProcess } from 'node:child_process'
import path from 'node:path'
import { findRepoRoot, freePort, killEngine, spawnEngine, waitForHealth } from './sidecar'

const DEV = !app.isPackaged
let child: ChildProcess | null = null
let win: BrowserWindow | null = null
let engineReady = false

const sleep = (ms: number): Promise<void> => new Promise((r) => setTimeout(r, ms))

// Drive the splash's step list from the real boot stages (best-effort: ignore if the splash page
// has already been replaced by the dashboard). Steps: 0 spawn · 1 health · 2 calibrator · 3 ready.
function splashStep(n: number, failed = false): void {
  const fn = failed ? '__setFail' : '__setStep'
  void win?.webContents.executeJavaScript(`window.${fn}&&window.${fn}(${n})`).catch(() => {})
}

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
  // Writable engine data lives in the per-user app-data dir in prod (the install dir under Program
  // Files is read-only), and in the repo's data_store in dev so the working store is reused.
  const dataDir = DEV ? path.join(repoRoot, 'data_store') : path.join(app.getPath('userData'), 'engine-data')
  child = spawnEngine(port, { dev: DEV, repoRoot, enginePath, dataDir })
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
  splashStep(1) // engine spawned; now polling /health
  engineReady = await waitForHealth(base, 30_000)
  console.log(`[boot] /health ${engineReady ? 'green' : 'TIMEOUT'} after ${Date.now() - t0}ms`)

  if (engineReady) {
    // Health green means the engine came up with its calibrator loaded; show the last stages
    // briefly so the readiness sequence is legible before the dashboard replaces the splash.
    splashStep(2)
    await sleep(320)
    splashStep(3)
    await sleep(200)
  } else {
    splashStep(1, true) // health timed out — mark the check failed; the app shows engine-down
    await sleep(400)
  }

  // Only now load the dashboard — a cold start never shows the UI before /health resolves. If it
  // timed out, the app still loads and its /health poll renders the engine-down state.
  if (DEV) {
    await win.loadURL('http://localhost:5173')
  } else {
    // electron-builder copies the built PWA to resources/pwa/ (extraResources).
    await win.loadFile(path.join(process.resourcesPath, 'pwa', 'index.html'))
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
