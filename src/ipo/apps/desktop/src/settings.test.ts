// Persistence test for the durable UI-settings store. Exercises the exact restart contract: a
// changed setting written to the user-data dir must be read back after a fresh load (= app close +
// reopen). Pure Node (settings.ts imports no electron), run via `node --test` — see package.json.

import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { test } from 'node:test'
import { type AppSettings, DEFAULT_NOTIF, loadSettings, normalizeUi, saveSettings } from './settings'

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
    })
    // The retained value is genuinely the user's choice, not a default that happens to match.
    assert.notDeepEqual(reopened.ui?.notifications, DEFAULT_NOTIF)
    assert.equal(reopened.ui?.theme, 'light')
    assert.equal(reopened.ui?.costs.dp, 22)
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
  } finally {
    fs.rmSync(dir, { recursive: true, force: true })
  }
})
