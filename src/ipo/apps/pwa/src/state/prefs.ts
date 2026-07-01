// Persisted UI preferences (localStorage), mirroring the comp. Theme is applied to the document
// root as data-theme ("system" follows prefers-color-scheme); density toggles a body class.

export type ThemeMode = 'dark' | 'light' | 'system'
export type Density = 'comfortable' | 'compact'

const KEY = 'ipoadv'

interface Prefs {
  theme: ThemeMode
  density: Density
}

function load(): Prefs {
  try {
    const p = JSON.parse(localStorage.getItem(KEY) ?? '{}')
    return {
      theme: p.theme === 'light' || p.theme === 'system' ? p.theme : 'dark',
      density: p.density === 'compact' ? 'compact' : 'comfortable',
    }
  } catch {
    return { theme: 'dark', density: 'comfortable' }
  }
}

let prefs = load()

function save() {
  try {
    localStorage.setItem(KEY, JSON.stringify(prefs))
  } catch {
    /* ignore quota / disabled storage */
  }
}

export const getThemeMode = (): ThemeMode => prefs.theme
export const getDensity = (): Density => prefs.density

export function resolveTheme(mode: ThemeMode): 'dark' | 'light' {
  if (mode === 'system') {
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
  }
  return mode
}

export function applyTheme(mode: ThemeMode, animate = false): void {
  const root = document.documentElement
  if (animate) {
    root.classList.add('theme-anim')
    window.setTimeout(() => root.classList.remove('theme-anim'), 520)
  }
  root.setAttribute('data-theme', resolveTheme(mode))
}

export function setThemeMode(mode: ThemeMode): void {
  prefs = { ...prefs, theme: mode }
  save()
  applyTheme(mode, true)
}

export function applyDensity(density: Density = prefs.density): void {
  document.body.classList.toggle('compact', density === 'compact')
}

export function setDensity(density: Density): void {
  prefs = { ...prefs, density }
  save()
  applyDensity(density)
}
