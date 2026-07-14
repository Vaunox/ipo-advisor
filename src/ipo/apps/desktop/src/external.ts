// External-open host allowlist (v3 V3-5/V3-6). Every URL handed to shell:openExternal comes from the
// per-IPO context cache — a DATA-PLANE value from upstream. An https check proves "this is https"; it
// does NOT prove the destination is one we can vouch for. A changed/poisoned cache entry would
// otherwise open an attacker-chosen page in the user's real browser. So we PIN the hosts we open, and
// refuse everything else (the UI shows an unpinned URL as inert, copyable text). Structural, like the
// model boundary. Electron-free so it is unit-testable via `node --test` (see external.test.ts).
//
// This is the AUTHORITATIVE security control (enforced in the main process). The renderer mirrors the
// same lists only to decide button-vs-inert rendering; if the two ever drift the worst case is a
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

// Document hosts — the RHP (v3 V3-5). Issuers host their own RHPs on unbounded domains, so we cannot
// allowlist those; only the official regulator filing host is pinned. An issuer-hosted RHP therefore
// renders as inert copyable text (safe), while the common SEBI-filed RHP opens one-click.
export const DOCUMENT_HOSTS = [
  'sebi.gov.in', // Securities and Exchange Board of India — official offer-document filings
] as const

const ALLOWED = [...REGISTRAR_HOSTS, ...DOCUMENT_HOSTS]

/** True only for an https URL whose host is (a subdomain of) a pinned registrar or document host.
 *  Everything else — unknown/issuer hosts, look-alikes, non-https, garbage — is refused. */
export function isAllowedExternalUrl(url: string): boolean {
  let host: string
  try {
    const u = new URL(url)
    if (u.protocol !== 'https:') return false
    host = u.hostname.toLowerCase()
  } catch {
    return false
  }
  return ALLOWED.some((d) => host === d || host.endsWith('.' + d))
}
