// Persistence test for the durable UI-settings store. Exercises the exact restart contract: a
// changed setting written to the user-data dir must be read back after a fresh load (= app close +
// reopen). Pure Node (settings.ts imports no electron), run via `node --test` — see package.json.

import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { test } from 'node:test'
import {
  type AppSettings,
  AUTOSTART_MARKER,
  DEFAULT_NOTIF,
  DEFAULT_STARTUP,
  type StartupPrefs,
  buildWebPreferences,
  loadSettings,
  loginItemSettings,
  normalizeUi,
  planStartupMigration,
  saveSettings,
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
