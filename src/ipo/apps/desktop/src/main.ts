import { app, BrowserWindow, ipcMain, Menu, nativeImage, Tray } from 'electron'
import { type ChildProcess } from 'node:child_process'
import path from 'node:path'
import { findRepoRoot, freePort, killEngine, spawnEngine, waitForHealth } from './sidecar'
import { type AppSettings, type StartupPrefs, loadSettings, saveSettings } from './settings'

const DEV = !app.isPackaged
let child: ChildProcess | null = null
let win: BrowserWindow | null = null
let tray: Tray | null = null
let engineReady = false
let isQuitting = false

let repoRoot = ''
let userDataDir = ''
let enginePort = 0
let engineBase = ''
let enginePath = ''
let iconPath = ''
let settings: AppSettings

// Windows uses this to attribute native notifications (and taskbar grouping) to the app.
app.setAppUserModelId('com.ipoadvisor.app')

const sleep = (ms: number): Promise<void> => new Promise((r) => setTimeout(r, ms))

// Drive the splash's step list from the real boot stages (best-effort: ignore if the splash page
// has already been replaced by the dashboard). Steps: 0 spawn · 1 health · 2 calibrator · 3 ready.
function splashStep(n: number, failed = false): void {
  const fn = failed ? '__setFail' : '__setStep'
  void win?.webContents.executeJavaScript(`window.${fn}&&window.${fn}(${n})`).catch(() => {})
}

// Spawn the engine sidecar and wire its logging. Reused for the in-app "Restart engine" action.
function startEngine(port: number): ChildProcess {
  // Writable engine data lives in the per-user app-data dir in prod (Program Files is read-only);
  // dev reuses the repo's data_store so the working store is shared.
  const dataDir = DEV ? path.join(repoRoot, 'data_store') : path.join(app.getPath('userData'), 'engine-data')
  const c = spawnEngine(port, { dev: DEV, repoRoot, enginePath, dataDir })
  c.stdout?.on('data', (d) => console.log(`[engine] ${String(d).trim()}`))
  c.stderr?.on('data', (d) => console.error(`[engine] ${String(d).trim()}`))
  c.on('exit', (code) => console.error(`[engine] exited (code ${code})`))
  return c
}

// Kill and respawn the sidecar on the SAME port so the renderer's engine base stays valid; the
// renderer's /health poll rides through the gap. Returns whether health came back green.
async function restartEngine(): Promise<boolean> {
  console.log('[engine] restart requested')
  killEngine(child)
  await sleep(600)
  child = startEngine(enginePort)
  engineReady = await waitForHealth(engineBase, 30_000)
  console.log(`[engine] restart /health ${engineReady ? 'green' : 'TIMEOUT'}`)
  return engineReady
}

function showWindow(): void {
  if (!win) return
  if (win.isMinimized()) win.restore()
  win.show()
  win.focus()
}

function persistBounds(): void {
  if (!win || win.isDestroyed()) return
  const b = win.getNormalBounds()
  settings.bounds = { x: b.x, y: b.y, width: b.width, height: b.height, maximized: win.isMaximized() }
  saveSettings(userDataDir, settings)
}

function createTray(): void {
  try {
    const image = nativeImage.createFromPath(iconPath)
    tray = new Tray(image.isEmpty() ? iconPath : image)
    tray.setToolTip('IPO Advisor')
    tray.setContextMenu(
      Menu.buildFromTemplate([
        { label: 'Open IPO Advisor', click: () => showWindow() },
        { label: 'Restart engine', click: () => void restartEngine() },
        { type: 'separator' },
        {
          label: 'Quit',
          click: () => {
            isQuitting = true
            app.quit()
          },
        },
      ]),
    )
    tray.on('click', () => showWindow())
  } catch (e) {
    console.error('[tray] failed', e)
  }
}

async function boot(): Promise<void> {
  repoRoot = findRepoRoot(__dirname)
  userDataDir = app.getPath('userData')
  settings = loadSettings(userDataDir)
  enginePort = await freePort()
  engineBase = `http://127.0.0.1:${enginePort}`
  console.log(`[boot] engine base ${engineBase} (dev=${DEV})`)

  // Prod runs the bundled PyInstaller binary shipped as an extraResource under resources/engine/.
  enginePath = path.join(
    process.resourcesPath ?? '',
    'engine',
    process.platform === 'win32' ? 'ipo-engine.exe' : 'ipo-engine',
  )
  // Window/taskbar icon (the exe isn't rcedited in the unsigned build, so set it at runtime).
  iconPath = DEV
    ? path.join(__dirname, '..', 'build', 'icon.ico')
    : path.join(process.resourcesPath, 'icon.ico')

  child = startEngine(enginePort)

  const saved = settings.bounds
  win = new BrowserWindow({
    width: saved?.width ?? 1320,
    height: saved?.height ?? 860,
    x: saved?.x,
    y: saved?.y,
    minWidth: 1040,
    minHeight: 700,
    backgroundColor: '#0a0d12',
    title: 'IPO Advisor',
    icon: iconPath,
    autoHideMenuBar: true,
    show: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      additionalArguments: [`--engine-base=${engineBase}`],
    },
  })
  if (saved?.maximized) win.maximize()

  // Start minimized (to the tray if enabled, else to the taskbar) when the operator asked for it.
  win.once('ready-to-show', () => {
    if (settings.startup.startMinimized) {
      if (!settings.startup.minimizeToTray) win?.minimize()
    } else {
      win?.show()
    }
  })

  // Close = minimize to tray (keep the engine warm) unless we're really quitting or the pref is off.
  win.on('close', (e) => {
    persistBounds()
    if (!isQuitting && settings.startup.minimizeToTray) {
      e.preventDefault()
      win?.hide()
    }
  })
  win.on('resized', persistBounds)
  win.on('moved', persistBounds)

  createTray()

  // Show the splash (the readiness gate, made visible) while we wait — the dashboard is NOT loaded.
  await win.loadFile(path.join(__dirname, '..', 'splash.html'))

  const t0 = Date.now()
  splashStep(1) // engine spawned; now polling /health
  engineReady = await waitForHealth(engineBase, 30_000)
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

// --- advisory-only IPC: OS integration + sidecar restart (never a verdict/order) --------------

ipcMain.handle('startup:get', (): StartupPrefs => settings.startup)

ipcMain.handle('startup:set', (_e, prefs: StartupPrefs): void => {
  settings.startup = { ...settings.startup, ...prefs }
  saveSettings(userDataDir, settings)
  // Registering a login item only makes sense for the installed app (not the dev electron.exe).
  if (!DEV) app.setLoginItemSettings({ openAtLogin: settings.startup.launchOnStartup })
})

ipcMain.handle('engine:restart', (): Promise<boolean> => restartEngine())

app.whenReady().then(boot).catch((e) => console.error('[boot] failed', e))

// Clean teardown on every exit path — no orphaned python (the classic Electron+sidecar bug).
app.on('window-all-closed', () => {
  // With minimize-to-tray the window only hides, so this won't fire; otherwise closing quits.
  if (!settings?.startup.minimizeToTray) {
    killEngine(child)
    app.quit()
  }
})
app.on('before-quit', () => {
  isQuitting = true
  killEngine(child)
})
app.on('will-quit', () => killEngine(child))
process.on('exit', () => killEngine(child))
process.on('SIGINT', () => {
  killEngine(child)
  process.exit(0)
})
