// Security test for the external-open allowlist (v3 V3-5/V3-6) — the one place a data-plane value
// drives a real-world action (opening a page the user may type a PAN into, or an RHP document). A
// registrar URL outside the allowlist MUST fail to open; an RHP only needs to be https. Electron-free,
// run via `node --test` (see package.json).

import assert from 'node:assert/strict'
import { test } from 'node:test'
import { isAllowedExternalUrl, isAllowedRhpUrl } from './external'

test('allows the pinned registrar hosts and their subdomains (PAN pages)', () => {
  for (const url of [
    'https://in.mpms.mufg.com/', // MUFG Intime (subdomain)
    'https://mpms.mufg.com/', // apex
    'https://www.bigshareonline.com/ipo/allotment',
    'https://kosmic.kfintech.com/', // KFin allotment subdomain
    'https://kfintech.com/',
    'https://linkintime.co.in/',
    'https://www.cameoindia.com/',
  ]) {
    assert.equal(isAllowedExternalUrl(url), true, url)
  }
})

test('refuses an unknown registrar host even over https (the poisoned-cache case)', () => {
  for (const url of [
    'https://evil.example.com/phish', // arbitrary attacker page
    'https://kfintech.com.evil.com/', // look-alike: registrar domain as a left-label
    'https://notkfintech.com/', // look-alike: not a subdomain boundary
    'https://mufg.com/', // parent bank domain, not the pinned registrar host
    'https://laserpowerinfra.com/rhp.pdf', // an issuer site — not a registrar host, refused here
    'https://www.sebi.gov.in/filings/public-issues/x-rhp', // a document host, not a registrar host
  ]) {
    assert.equal(isAllowedExternalUrl(url), false, url)
  }
})

test('refuses non-https and non-URLs (registrar check)', () => {
  for (const url of [
    'http://in.mpms.mufg.com/', // downgraded scheme
    'javascript:alert(1)',
    'file:///etc/passwd',
    'not a url',
    '',
  ]) {
    assert.equal(isAllowedExternalUrl(url), false, url)
  }
})

test('isAllowedRhpUrl allows any https URL — issuer-hosted or the official SEBI filing alike', () => {
  for (const url of [
    'https://www.sebi.gov.in/filings/public-issues/x-rhp',
    'https://sebi.gov.in/sebi_data/attachdocs/y.pdf',
    'https://laserpowerinfra.com/rhp.pdf', // issuer-hosted — no PAN entry, so no host pin needed
    'https://an-arbitrary-issuer-domain.example/offer-documents/rhp.pdf',
  ]) {
    assert.equal(isAllowedRhpUrl(url), true, url)
  }
})

test('isAllowedRhpUrl refuses non-https and non-URLs', () => {
  for (const url of [
    'http://www.sebi.gov.in/x', // downgraded scheme
    'javascript:alert(1)',
    'file:///etc/passwd',
    'not a url',
    '',
  ]) {
    assert.equal(isAllowedRhpUrl(url), false, url)
  }
})
