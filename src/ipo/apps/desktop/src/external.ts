// External-open allowlist (v3 V3-5/V3-6). Every URL handed to shell:openExternal comes from the
// per-IPO context cache — a DATA-PLANE value from upstream. An https check proves "this is https"; it
// does NOT prove the destination is one we can vouch for. A changed/poisoned cache entry would
// otherwise open an attacker-chosen page in the user's real browser.
//
// Two different trust bars, gated separately: a registrar portal is where the user enters their PAN,
// so it must be a PINNED host (isAllowedExternalUrl) — everything else refused (the UI shows an
// unpinned URL as inert, copyable text). An RHP is a public regulatory filing with no PAN entry, so
// any https URL is fine (isAllowedRhpUrl) — every RHP opens one-click, issuer-hosted or not.
// Structural, like the model boundary. Electron-free so it is unit-testable via `node --test`.
//
// This is the AUTHORITATIVE security control (enforced in the main process). The renderer mirrors the
// same rules only to decide button-vs-inert rendering; if the two ever drift the worst case is a
// cosmetic mismatch — the open is still gated here.

// Registrar portals — where the user enters their PAN, so the tightest list (v3 V3-6).
export const REGISTRAR_HOSTS = [
  'mpms.mufg.com', // MUFG Intime (formerly Link Intime) — e.g. in.mpms.mufg.com
  'linkintime.co.in', // Link Intime India
  'kfintech.com', // KFin Technologies
  'bigshareonline.com', // Bigshare Services
  'maashitla.com', // Maashitla Securities
  'skylinerta.com', // Skyline Financial Services
  'cameoindia.com', // Cameo Corporate Services
  'purvashare.com', // Purva Sharegistry
] as const

/** True only for an https URL whose host is (a subdomain of) a pinned registrar host.
 *  Everything else — unknown hosts, look-alikes, non-https, garbage — is refused. */
export function isAllowedExternalUrl(url: string): boolean {
  let host: string
  try {
    const u = new URL(url)
    if (u.protocol !== 'https:') return false
    host = u.hostname.toLowerCase()
  } catch {
    return false
  }
  return REGISTRAR_HOSTS.some((d) => host === d || host.endsWith('.' + d))
}

/** An RHP is a public regulatory filing, not a PAN-entry surface — any https URL is fine to open. */
export function isAllowedRhpUrl(url: string): boolean {
  try {
    return new URL(url).protocol === 'https:'
  } catch {
    return false
  }
}

// Navigation lockdown (review #5). The app window only ever shows its OWN dashboard: approved
// external links open in the OS browser via shell.openExternal (a separate path), never in-window.
// So in-window navigation is fail-closed — allow ONLY the app's own origin, deny everything else.
// Electron-free so it is unit-tested via `node --test`, like the allowlists above.
export interface NavPolicy {
  /** Dev: the app's own dev-server URL (its origin is the allow key, e.g. 'http://localhost:5173').
   *  Null in prod. */
  devServerUrl: string | null
  /** Prod: the file:// URL the app loads; navigation is allowed only to its pathname. Empty in dev. */
  appFileUrl: string
}

/** True only for a navigation that stays inside the app's own origin — the dev server in dev, or the
 *  loaded PWA file's pathname in prod. ``file://`` origins are all ``"null"``, so pathname is the
 *  identity there (a reload carrying a ``#route``/query is still allowed); any OTHER file path is
 *  denied. External https, a different localhost port, and non-URLs are all denied. Fail-closed. */
export function isAllowedNavigation(target: string, policy: NavPolicy): boolean {
  let t: URL
  try {
    t = new URL(target)
  } catch {
    return false // not a parseable URL → deny
  }
  if (policy.devServerUrl) {
    try {
      return t.origin === new URL(policy.devServerUrl).origin // dev: the app's own origin only
    } catch {
      return false
    }
  }
  if (t.protocol !== 'file:') return false // prod: only local files
  try {
    return t.pathname === new URL(policy.appFileUrl).pathname // ...and only the loaded PWA's own path
  } catch {
    return false
  }
}
