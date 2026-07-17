// The renderer's mirror of the external-open allowlist — decides button-vs-inert rendering only
// (the AUTHORITATIVE check lives in apps/desktop/src/external.ts). registrarAllotmentUrl carries
// real mapping logic (which curated URL each pinned registrar resolves to), worth locking down.

import assert from 'node:assert/strict'
import { test } from 'node:test'
import { isAllowedExternalUrl, isAllowedRhpUrl, registrarAllotmentUrl } from './external.ts'

test('isAllowedExternalUrl allows only the pinned registrar hosts', () => {
  assert.equal(isAllowedExternalUrl('https://kfintech.com/'), true)
  assert.equal(isAllowedExternalUrl('https://ipostatus.kfintech.com/'), true)
  assert.equal(isAllowedExternalUrl('https://www.sebi.gov.in/x'), false) // document host, not registrar
  assert.equal(isAllowedExternalUrl('https://evil.example.com/'), false)
  assert.equal(isAllowedExternalUrl(null), false)
})

test('isAllowedRhpUrl allows any https URL, issuer-hosted included', () => {
  assert.equal(isAllowedRhpUrl('https://www.sebi.gov.in/filings/x'), true)
  assert.equal(isAllowedRhpUrl('https://an-issuer.example/rhp.pdf'), true)
  assert.equal(isAllowedRhpUrl('http://an-issuer.example/rhp.pdf'), false) // downgraded scheme
  assert.equal(isAllowedRhpUrl(null), false)
})

test('registrarAllotmentUrl resolves every pinned registrar to its curated check-allotment page', () => {
  const cases: [string, string][] = [
    ['https://www.linkintime.co.in/', 'https://in.mpms.mufg.com/Initial_Offer/public-issues.html'],
    ['https://kfintech.com/', 'https://ipostatus.kfintech.com/'],
    ['https://www.bigshareonline.com/', 'https://www.bigshareonline.com/ipo_allotment.html'],
    ['https://in.mpms.mufg.com/', 'https://in.mpms.mufg.com/Initial_Offer/public-issues.html'],
    ['https://maashitla.com/', 'https://maashitla.com/allotment-status/public-issues'],
    ['https://skylinerta.com/', 'https://www.skylinerta.com/display_ipo_rightissue_allotment.php'],
    ['https://cameoindia.com/', 'https://cambridge.cameoindia.com/'],
    ['https://purvashare.com/', 'https://www.purvashare.com/investor-service/ipo-query'],
  ]
  for (const [cachedWebsite, expected] of cases) {
    assert.equal(registrarAllotmentUrl(cachedWebsite), expected, cachedWebsite)
  }
})

test('registrarAllotmentUrl ignores the cached URL path — only the host selects the destination', () => {
  // Even if the cache happened to already carry a deep path, we substitute our own curated one.
  assert.equal(
    registrarAllotmentUrl('https://kfintech.com/some/other/page'),
    'https://ipostatus.kfintech.com/',
  )
})

test('registrarAllotmentUrl returns null for an unrecognized host or missing value', () => {
  assert.equal(registrarAllotmentUrl('https://evil.example.com/'), null)
  assert.equal(registrarAllotmentUrl('not a url'), null)
  assert.equal(registrarAllotmentUrl(null), null)
})
