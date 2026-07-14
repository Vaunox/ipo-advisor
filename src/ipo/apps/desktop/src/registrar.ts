// Registrar host allowlist (v3 V3-6). The URL handed to shell:openExternal comes from the registrar
// cache — a DATA-PLANE value from upstream. An https check proves "this is https"; it does NOT prove
// "this is a registrar". A changed or poisoned cache entry would otherwise open an attacker-chosen
// https page in the user's real browser, with the user primed to type their PAN into it. That is the
// one place a data-plane value drives a real-world action, so we close it structurally: only the
// known Indian IPO registrars' hosts may open; anything else is refused (the UI shows it as inert,
// copyable text instead). Electron-free so it is unit-testable via `node --test` (see registrar.test.ts).
//
// This is the AUTHORITATIVE security control (enforced in the main process). The renderer mirrors the
// same host list only to decide button-vs-inert rendering; if the two ever drift the worst case is a
// cosmetic mismatch — the open is still gated here.
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

/** True only for an https URL whose host is (a subdomain of) a pinned registrar. Everything else —
 *  unknown hosts, look-alikes, non-https, garbage — is refused. */
export function isAllowedRegistrarUrl(url: string): boolean {
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
