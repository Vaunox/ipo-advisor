// External-open allowlist + opener (v3 V3-5/V3-6). Mirrors the AUTHORITATIVE list in
// apps/desktop/src/external.ts — used here ONLY to decide button-vs-inert rendering; the main process
// re-validates every open, so if the two lists drift the worst case is cosmetic, not a security hole.
//
// Two different trust bars: a registrar portal is where the user may type a PAN, so it must be a
// PINNED host (isAllowedExternalUrl) — an unrecognized registrar cache URL renders as inert,
// copyable text, never a working "open". An RHP is a public regulatory filing with no PAN entry, so
// any https URL is fine to open (isAllowedRhpUrl) — every RHP gets the same live button, regardless
// of whether the issuer hosts it themselves or SEBI does.

const REGISTRAR_HOSTS = [
  'mpms.mufg.com',
  'linkintime.co.in',
  'kfintech.com',
  'bigshareonline.com',
  'maashitla.com',
  'skylinerta.com',
  'cameoindia.com',
  'purvashare.com',
]

export function isAllowedExternalUrl(url: string | null): url is string {
  if (!url) return false
  try {
    const u = new URL(url)
    if (u.protocol !== 'https:') return false
    const h = u.hostname.toLowerCase()
    return REGISTRAR_HOSTS.some((d) => h === d || h.endsWith('.' + d))
  } catch {
    return false
  }
}

// Any https URL is fine for an RHP — it's a public filing, never a PAN-entry surface.
export function isAllowedRhpUrl(url: string | null): url is string {
  if (!url) return false
  try {
    return new URL(url).protocol === 'https:'
  } catch {
    return false
  }
}

// The upstream context cache's registrar `website` field is often just the registrar's general
// homepage, not their specific "check allotment status" sub-page — verified against each
// registrar's own site. For our fixed, pinned set of registrars we know the correct destination, so
// we substitute it in rather than trust the cached URL's exact path. Keyed by the SAME hosts as
// REGISTRAR_HOSTS, so a resolved URL always also passes isAllowedExternalUrl.
const REGISTRAR_ALLOTMENT_URL: Record<string, string> = {
  'linkintime.co.in': 'https://linkintime.co.in/initial_offer/public-issues.html',
  'kfintech.com': 'https://ipostatus.kfintech.com/',
  'bigshareonline.com': 'https://www.bigshareonline.com/ipo_allotment.html',
  'mpms.mufg.com': 'https://in.mpms.mufg.com/Initial_Offer/public-issues.html',
  'maashitla.com': 'https://maashitla.com/allotment-status/public-issues',
  'skylinerta.com': 'https://www.skylinerta.com/display_ipo_rightissue_allotment.php',
  'cameoindia.com': 'https://ipo.cameoindia.com/',
  'purvashare.com': 'https://www.purvashare.com/investor-service/ipo-query',
}

// Resolve a registrar's cached `website` to its curated allotment-status page, by matching the
// cached URL's HOST against our pinned registrar list — never trusting the cached URL's path.
// Returns null when the host isn't one of ours (isAllowedExternalUrl already refuses to open it).
export function registrarAllotmentUrl(website: string | null): string | null {
  if (!website) return null
  let host: string
  try {
    host = new URL(website).hostname.toLowerCase()
  } catch {
    return null
  }
  const pinned = REGISTRAR_HOSTS.find((d) => host === d || host.endsWith('.' + d))
  return pinned ? REGISTRAR_ALLOTMENT_URL[pinned] : null
}

interface DesktopBridge {
  openExternal?: (url: string, kind: 'registrar' | 'rhp') => Promise<boolean>
}

// Open an allowlisted URL in the user's real browser. Desktop routes through the shell (which
// re-validates the URL against `kind`'s rule); browser/dev falls back to a new tab. Only call for a
// URL that already passed isAllowedExternalUrl (kind 'registrar') or isAllowedRhpUrl (kind 'rhp').
export function openExternalUrl(url: string, kind: 'registrar' | 'rhp'): void {
  const api = (window as unknown as { ipoDesktop?: DesktopBridge }).ipoDesktop
  if (api?.openExternal) void api.openExternal(url, kind)
  else window.open(url, '_blank', 'noopener,noreferrer')
}
