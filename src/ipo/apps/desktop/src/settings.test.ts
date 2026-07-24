// Persistence test for the durable UI-settings store. Exercises the exact restart contract: a
// changed setting written to the user-data dir must be read back after a fresh load (= app close +
// reopen). Pure Node (settings.ts imports no electron), run via `node --test` — see package.json.

import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { mock, test } from 'node:test'
import {
  type AppSettings,
  type SeenState,
  AUTOSTART_MARKER,
  DEFAULT_NOTIF,
  DEFAULT_STARTUP,
  type StartupPrefs,
  PERSIST_BOUNDS_EVENTS,
  boundsToPersist,
  buildWebPreferences,
  loadSeenState,
  loadSettings,
  loginItemSettings,
  normalizeUi,
  planStartupMigration,
  saveSeenState,
  saveSettings,
  startupWindowState,
  wasAutoLaunched,
} from './settings'

function tmpUserDataDir(): string {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'ipoadv-settings-'))
}

test('a changed UI setting survives a simulated restart (write -> reload -> retained)', () => {
  const dir = tmpUserDataDir()
  try {
    // Fresh install: no config file yet, so UI prefs are undefined (the renderer would migrate its
    // localStorage on first run). This is the pre-change baseline.
    assert.equal(loadSettings(dir).ui, undefined)

    // The user changes settings across every category: theme, density, broker costs, all four
    // notification toggles flipped off-defaults, and a pinned IPO.
    const changed: AppSettings = {
      startup: loadSettings(dir).startup,
      ui: normalizeUi({
        theme: 'light',
        density: 'compact',
        costs: { stt: 0.2, dp: 22, oth: 0.09 },
        notifications: { native: false, applyCrossing: false, anyChange: true, quiet: false },
        pinned: ['ipo-xyz'],
        awaitingCollapsed: true, // v3 V3-14: a non-default fold must survive the restart
        devConsole: true, // v3 V3-16: a non-default console-enable must survive the restart too
      }),
    }
    saveSettings(dir, changed)

    // Simulate closing and reopening the app: a brand-new load from the same user-data dir.
    const reopened = loadSettings(dir)

    assert.deepEqual(reopened.ui, {
      theme: 'light',
      density: 'compact',
      costs: { stt: 0.2, dp: 22, oth: 0.09 },
      notifications: { native: false, applyCrossing: false, anyChange: true, quiet: false },
      pinned: ['ipo-xyz'],
      awaitingCollapsed: true,
      devConsole: true,
    })
    // The retained value is genuinely the user's choice, not a default that happens to match.
    assert.notDeepEqual(reopened.ui?.notifications, DEFAULT_NOTIF)
    assert.equal(reopened.ui?.theme, 'light')
    assert.equal(reopened.ui?.costs.dp, 22)
    assert.equal(reopened.ui?.awaitingCollapsed, true) // the "awaiting" fold survived the reopen
    assert.equal(reopened.ui?.devConsole, true) // the console-enable survived the reopen
  } finally {
    fs.rmSync(dir, { recursive: true, force: true })
  }
})

// --- OP-1: start-minimized applies only on auto-launch (marker arg + one-time migration) ---------

test('wasAutoLaunched detects the marker arg only when present in argv', () => {
  // A packaged manual open: no marker -> a manual launch always shows the window.
  assert.equal(wasAutoLaunched(['C:/Program Files/IPO Advisor/IPO Advisor.exe']), false)
  // Windows auto-launch at login: Electron passes the registered marker arg.
  assert.equal(
    wasAutoLaunched(['C:/Program Files/IPO Advisor/IPO Advisor.exe', AUTOSTART_MARKER]),
    true,
  )
  // Order/other args don't matter; it's a membership test, not positional.
  assert.equal(wasAutoLaunched(['electron', '.', AUTOSTART_MARKER, '--other']), true)
  assert.equal(wasAutoLaunched([]), false)
})

test('loginItemSettings always carries the marker; openAtLogin mirrors the pref', () => {
  const on = loginItemSettings({ ...DEFAULT_STARTUP, launchOnStartup: true })
  assert.equal(on.openAtLogin, true)
  assert.deepEqual(on.args, [AUTOSTART_MARKER]) // an auto-launch stays detectable

  const off = loginItemSettings({ ...DEFAULT_STARTUP, launchOnStartup: false })
  assert.equal(off.openAtLogin, false) // unregister
  assert.deepEqual(off.args, [AUTOSTART_MARKER]) // marker still present (moot when off, but consistent)
})

test('planStartupMigration re-registers an existing launch-on-startup user exactly once', () => {
  const existing: StartupPrefs = { ...DEFAULT_STARTUP, launchOnStartup: true } // pre-OP-1: no flag

  const first = planStartupMigration(existing, false)
  assert.equal(first.register, true) // re-register the login item WITH the marker
  assert.equal(first.changed, true) // prefs changed -> persist
  assert.equal(first.next.startupMigrated, true) // and record that it ran

  // Second boot (already migrated): a strict no-op — no re-register, no change.
  const second = planStartupMigration(first.next, false)
  assert.equal(second.register, false)
  assert.equal(second.changed, false)
  assert.equal(second.next, first.next) // same reference back — nothing to persist
})

test('planStartupMigration records-only for a user who never enabled launch-on-startup', () => {
  const first = planStartupMigration({ ...DEFAULT_STARTUP, launchOnStartup: false }, false)
  assert.equal(first.register, false) // nothing to register
  assert.equal(first.changed, true) // but still mark migrated so we never re-check on boot
  assert.equal(first.next.startupMigrated, true)
})

test('planStartupMigration never touches the login item in dev', () => {
  const dev = planStartupMigration({ ...DEFAULT_STARTUP, launchOnStartup: true }, true)
  assert.equal(dev.register, false)
  assert.equal(dev.changed, false) // dev never registers a login item, and never persists the flag
})

test('the migration flag survives a save -> reload (never re-runs after first boot)', () => {
  const dir = tmpUserDataDir()
  try {
    // Simulate the migration having run: persist startup with the flag set.
    const migrated: AppSettings = {
      startup: { ...DEFAULT_STARTUP, launchOnStartup: true, startupMigrated: true },
    }
    saveSettings(dir, migrated)

    const reloaded = loadSettings(dir)
    assert.equal(reloaded.startup.startupMigrated, true) // flag persisted
    assert.equal(planStartupMigration(reloaded.startup, false).changed, false) // -> no re-run
  } finally {
    fs.rmSync(dir, { recursive: true, force: true })
  }
})

test('a partial / hand-edited config falls back to defaults field-by-field', () => {
  const dir = tmpUserDataDir()
  try {
    fs.writeFileSync(
      path.join(dir, 'settings.json'),
      JSON.stringify({ startup: {}, ui: { theme: 'nonsense', costs: { stt: 0.3 } } }),
    )
    const s = loadSettings(dir)
    assert.equal(s.ui?.theme, 'dark') // invalid value -> default
    assert.equal(s.ui?.density, 'comfortable') // missing -> default
    assert.equal(s.ui?.costs.stt, 0.3) // provided -> kept
    assert.equal(s.ui?.costs.dp, 15.34) // missing -> default
    assert.deepEqual(s.ui?.notifications, DEFAULT_NOTIF) // missing -> defaults (nothing on)
    assert.deepEqual(s.ui?.pinned, []) // missing -> empty
    assert.equal(s.ui?.awaitingCollapsed, false) // missing -> default (expanded)
    assert.equal(s.ui?.devConsole, false) // missing -> default (console OFF)
  } finally {
    fs.rmSync(dir, { recursive: true, force: true })
  }
})

// --- F1-rev: the single window-visibility authority (startupWindowState) --------------------------
// One pure decision replaces the split logic (a `maximize()` call BEFORE ready-to-show + the handler)
// whose two disconnected authorities let a restore-maximized concern pre-empt start-minimized: on a
// maximized auto-launch the window opened fully (config 1) or flashed then minimized (config 2).
// All four outcomes fenced, plus the load-bearing invariants and the tray-failure degrade.

function stState(
  over: Partial<Parameters<typeof startupWindowState>[0]> = {},
): ReturnType<typeof startupWindowState> {
  // Base = config 1 (auto-launched, start-minimized, tray on, tray created). Each test overrides.
  return startupWindowState({
    autoLaunched: true,
    startMinimized: true,
    minimizeToTray: true,
    savedMaximized: false,
    trayAvailable: true,
    ...over,
  })
}

test('config 1 (auto + start-min + tray on) → hidden-to-tray, INDEPENDENT of savedMaximized', () => {
  // The bug was a maximized window forcing "shown" here. The leak is closed iff `savedMaximized` does
  // NOT change the outcome — both true and false must map to the same start-minimized outcome.
  assert.equal(stState({ savedMaximized: false }), 'hidden-to-tray')
  assert.equal(stState({ savedMaximized: true }), 'hidden-to-tray') // maximized no longer pre-empts it
})

test('config 2 (auto + start-min + tray OFF) → minimized-to-taskbar, INDEPENDENT of savedMaximized', () => {
  assert.equal(stState({ minimizeToTray: false, savedMaximized: false }), 'minimized-to-taskbar')
  assert.equal(stState({ minimizeToTray: false, savedMaximized: true }), 'minimized-to-taskbar')
})

test('regression guard: a maximized MANUAL open still reopens maximized', () => {
  assert.equal(stState({ autoLaunched: false, savedMaximized: true }), 'shown-maximized')
  assert.equal(stState({ autoLaunched: false, savedMaximized: false }), 'shown-normal')
})

test('OP-1 invariant: a manual open ALWAYS shows, even with start-minimized on', () => {
  // Start-minimized is honored ONLY on a real auto-launch; a manual double-click always shows.
  assert.equal(stState({ autoLaunched: false, startMinimized: true }), 'shown-normal')
  assert.equal(stState({ autoLaunched: false, startMinimized: true, savedMaximized: true }), 'shown-maximized')
})

test('tray-failure degrade: hidden-to-tray falls back to the taskbar when the tray is gone', () => {
  // If createTray() failed, hiding into the tray would leave the app unreachable — degrade to taskbar.
  assert.equal(stState({ minimizeToTray: true, trayAvailable: false }), 'minimized-to-taskbar')
  assert.equal(stState({ minimizeToTray: true, trayAvailable: true }), 'hidden-to-tray') // tray flips it
})

test('a normal (not start-minimized) auto-launch shows, maximize-aware', () => {
  assert.equal(stState({ startMinimized: false, savedMaximized: false }), 'shown-normal')
  assert.equal(stState({ startMinimized: false, savedMaximized: true }), 'shown-maximized')
})

// --- PR-A: persistBounds must fire on maximize/unmaximize, not only resized/moved ----------------

test('PERSIST_BOUNDS_EVENTS keeps bounds.maximized a live mirror (fixes the stale-maximized reopen)', () => {
  // maximize()/unmaximize() fire ONLY 'maximize'/'unmaximize', never 'resized' — so without these two
  // the persisted bounds.maximized only updated on a later drag or close, and a reopen with no
  // preceding close (a second-instance double-launch) could re-maximize a window the user un-maximized.
  assert.ok(PERSIST_BOUNDS_EVENTS.includes('maximize'), 'maximize must trigger a bounds persist')
  assert.ok(PERSIST_BOUNDS_EVENTS.includes('unmaximize'), 'unmaximize must trigger a bounds persist')
  // …and the pre-existing geometry triggers are not dropped:
  assert.ok(PERSIST_BOUNDS_EVENTS.includes('resized'))
  assert.ok(PERSIST_BOUNDS_EVENTS.includes('moved'))

  // Behavioural fence: replicate main.ts's registration over a fake window and confirm that firing the
  // maximize/unmaximize listener actually runs persistBounds — the effect the reopen relies on.
  const handlers = new Map<string, () => void>()
  const fakeWin = { on: (ev: string, l: () => void) => handlers.set(ev, l) }
  let persisted = 0
  for (const ev of PERSIST_BOUNDS_EVENTS) fakeWin.on(ev, () => (persisted += 1))
  handlers.get('maximize')?.()
  handlers.get('unmaximize')?.()
  assert.equal(persisted, 2, 'maximize + unmaximize each run persistBounds')
})

test('boundsToPersist skips while minimized — preserves the pre-minimize maximized flag', () => {
  const prev = { x: 1, y: 2, width: 900, height: 700, maximized: true }
  const normal = { x: 5, y: 6, width: 400, height: 300 }
  // Minimized: win.isMaximized() reads FALSE here — must NOT overwrite prev's maximized:true. Returns
  // the SAME ref so persistBounds skips the write (the maximize→minimize→close clobber guard).
  assert.equal(boundsToPersist({ minimized: true, maximized: false, normal }, prev), prev)
  // Not minimized + maximized → capture maximized:true.
  assert.deepEqual(boundsToPersist({ minimized: false, maximized: true, normal }, prev), {
    ...normal,
    maximized: true,
  })
  // Not minimized + normal → capture maximized:false.
  assert.deepEqual(boundsToPersist({ minimized: false, maximized: false, normal }, prev), {
    ...normal,
    maximized: false,
  })
})

// --- OP-6: the sealed-shell BrowserWindow posture (DevTools off in prod, on in dev) --------------

test('buildWebPreferences locks the security posture; DevTools tracks dev (OP-6)', () => {
  const opts = { preload: '/app/dist/preload.js', engineBase: 'http://127.0.0.1:5000' }

  const prod = buildWebPreferences(false, opts) // the packaged build
  assert.equal(prod.devTools, false) // OP-6: Chromium DevTools OFF in production (Ctrl+Shift+I inert)
  assert.equal(prod.contextIsolation, true) // sealed shell — must not regress
  assert.equal(prod.nodeIntegration, false) // sealed shell — must not regress
  // Behaviour-identical relocation: the fields that were inline before pass through unchanged.
  assert.equal(prod.preload, '/app/dist/preload.js')
  assert.deepEqual(prod.additionalArguments, ['--engine-base=http://127.0.0.1:5000'])

  const dev = buildWebPreferences(true, opts) // dev: developers still need DevTools
  assert.equal(dev.devTools, true)
  assert.equal(dev.contextIsolation, true) // posture identical in dev
  assert.equal(dev.nodeIntegration, false)
})

// --- OP-3: the seen-state durable store (seen-state.json) — separate from settings.json -----------

test('seen-state round-trips through save/load (survives a simulated restart)', () => {
  const dir = tmpUserDataDir()
  try {
    assert.equal(loadSeenState(dir), null) // absent -> null (the renderer then migrates its localStorage)
    const seen: SeenState = {
      alertsSeen: ['ipo-a', 'ipo-b'],
      notifiedCrossings: ['ipo-a@2026-07-20'],
      dismissedCrossings: ['ipo-b@2026-07-21'], // F12: dismissals must survive the restart too
      notifSeeded: true,
      lastSeen: { 'ipo-a': 'APPLY', 'ipo-b': 'SKIP' },
    }
    saveSeenState(dir, seen)
    // Reload from the same dir = app close + reopen: the seen-sets come back, not empty.
    assert.deepEqual(loadSeenState(dir), seen)
  } finally {
    fs.rmSync(dir, { recursive: true, force: true })
  }
})

test('F12: an older seen-state.json (no dismissedCrossings) hydrates it as [] — never vanishes/crashes', () => {
  const dir = tmpUserDataDir()
  try {
    // A file written before F12 has no dismissedCrossings key. loadSeenState parses field-by-field,
    // so the missing field must default to [] (nothing dismissed yet), not undefined or a throw.
    fs.writeFileSync(
      path.join(dir, 'seen-state.json'),
      JSON.stringify({
        alertsSeen: ['ipo-a'],
        notifiedCrossings: ['ipo-a@2026-07-20'],
        notifSeeded: true,
        lastSeen: { 'ipo-a': 'APPLY' },
      }),
      'utf-8',
    )
    assert.deepEqual(loadSeenState(dir)?.dismissedCrossings, [])
    assert.deepEqual(loadSeenState(dir)?.alertsSeen, ['ipo-a']) // the pre-existing fields still load
  } finally {
    fs.rmSync(dir, { recursive: true, force: true })
  }
})

test('a corrupt seen-state.json degrades to empty (never crashes boot/hydration)', () => {
  const dir = tmpUserDataDir()
  try {
    fs.writeFileSync(path.join(dir, 'seen-state.json'), '{ this is not valid json', 'utf-8')
    // Present-but-torn -> empty SeenState (start-fresh), NOT null and NOT a throw.
    assert.deepEqual(loadSeenState(dir), {
      alertsSeen: [],
      notifiedCrossings: [],
      dismissedCrossings: [],
      notifSeeded: false,
      lastSeen: {},
    })
  } finally {
    fs.rmSync(dir, { recursive: true, force: true })
  }
})

test('saveSeenState is ATOMIC: a failed rename leaves the last-good file intact (temp-then-rename)', () => {
  const dir = tmpUserDataDir()
  try {
    saveSeenState(dir, {
      alertsSeen: ['keep'],
      notifiedCrossings: [],
      dismissedCrossings: [],
      notifSeeded: true,
      lastSeen: {},
    })
    // Force the rename to fail: a DIRECT writeFileSync(target) would have already truncated+replaced
    // the target (reintroducing OP-3's torn-write bug); the atomic temp-then-rename must NOT — so this
    // also fails loudly if a future refactor drops the atomic idiom back to a direct write.
    const m = mock.method(fs, 'renameSync', () => {
      throw new Error('EPERM: simulated external lock (AV/indexer) on rename')
    })
    try {
      saveSeenState(dir, {
        alertsSeen: ['new'],
        notifiedCrossings: ['x'],
        dismissedCrossings: ['x@2026-07-21'],
        notifSeeded: false,
        lastSeen: {},
      })
    } finally {
      m.mock.restore()
    }
    // The target still holds the last-good data — the failed write did not corrupt/replace it.
    assert.deepEqual(loadSeenState(dir)?.alertsSeen, ['keep'])
    assert.equal(loadSeenState(dir)?.notifSeeded, true)
  } finally {
    fs.rmSync(dir, { recursive: true, force: true })
  }
})

test('saveSettings is ATOMIC: a failed rename leaves the last-good settings.json intact (temp-then-rename)', () => {
  const dir = tmpUserDataDir()
  try {
    saveSettings(dir, { startup: { ...DEFAULT_STARTUP, launchOnStartup: true } }) // known-good config
    // Force the rename to fail: a DIRECT writeFileSync(target) would have already truncated+replaced
    // the target; the atomic temp-then-rename must NOT — same fence as saveSeenState against a refactor
    // back to a direct write.
    const m = mock.method(fs, 'renameSync', () => {
      throw new Error('EPERM: simulated external lock (AV/indexer) on rename')
    })
    try {
      saveSettings(dir, { startup: { ...DEFAULT_STARTUP, launchOnStartup: false, minimizeToTray: false } })
    } finally {
      m.mock.restore()
    }
    // The target still holds the last-good config — the failed write did not corrupt/replace it.
    assert.equal(loadSettings(dir).startup.launchOnStartup, true)
  } finally {
    fs.rmSync(dir, { recursive: true, force: true })
  }
})
