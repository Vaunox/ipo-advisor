// External-open allowlist + opener (v3 V3-5/V3-6). Mirrors the AUTHORITATIVE list in
// apps/desktop/src/external.ts — used here ONLY to decide button-vs-inert rendering; the main process
// re-validates every open, so if the two lists drift the worst case is cosmetic, not a security hole.
// A cache URL (registrar portal or RHP) that isn't a pinned host renders as inert, copyable text —
// never a working "open" for a page (a PAN portal or an official document) we can't vouch for.

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
const DOCUMENT_HOSTS = ['sebi.gov.in'] // official RHP filing host; issuer-hosted RHPs stay inert
const ALLOWED = [...REGISTRAR_HOSTS, ...DOCUMENT_HOSTS]

export function isAllowedExternalUrl(url: string | null): url is string {
  if (!url) return false
  try {
    const u = new URL(url)
    if (u.protocol !== 'https:') return false
    const h = u.hostname.toLowerCase()
    return ALLOWED.some((d) => h === d || h.endsWith('.' + d))
  } catch {
    return false
  }
}

interface DesktopBridge {
  openExternal?: (url: string) => Promise<boolean>
}

// Open an allowlisted URL in the user's real browser. Desktop routes through the shell (which
// re-validates the host); browser/dev falls back to a new tab. Only call for isAllowedExternalUrl.
export function openExternalUrl(url: string): void {
  const api = (window as unknown as { ipoDesktop?: DesktopBridge }).ipoDesktop
  if (api?.openExternal) void api.openExternal(url)
  else window.open(url, '_blank', 'noopener,noreferrer')
}
