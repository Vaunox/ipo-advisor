// Security test for the external-open allowlist (v3 V3-5/V3-6) — the one place a data-plane value
// drives a real-world action (opening a page the user may type a PAN into, or an RHP document). A
// registrar URL outside the allowlist MUST fail to open; an RHP only needs to be https. Electron-free,
// run via `node --test` (see package.json).

import assert from 'node:assert/strict'
import { test } from 'node:test'
import { isAllowedExternalUrl, isAllowedNavigation, isAllowedRhpUrl } from './external'

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

// --- Navigation lockdown (review #5): allow only the app's own origin, deny everything else --------

const DEV_POLICY = { devServerUrl: 'http://localhost:5173', appFileUrl: '' }
const PROD_POLICY = { devServerUrl: null, appFileUrl: 'file:///C:/app/resources/pwa/index.html' }

test('nav lockdown (dev): allows the app\'s own dev-server origin, denies everything else', () => {
  assert.equal(isAllowedNavigation('http://localhost:5173/', DEV_POLICY), true)
  // a same-origin reload carrying a client route + query is still the app's own origin
  assert.equal(isAllowedNavigation('http://localhost:5173/x?a=1#/live', DEV_POLICY), true)
  assert.equal(isAllowedNavigation('https://evil.example.com/', DEV_POLICY), false) // external
  assert.equal(isAllowedNavigation('http://localhost:6006/', DEV_POLICY), false) // different port
  assert.equal(isAllowedNavigation('file:///C:/evil.html', DEV_POLICY), false) // a file, not the dev origin
  assert.equal(isAllowedNavigation('not a url', DEV_POLICY), false)
})

test('nav lockdown (prod): allows only the loaded PWA file path (incl. a #route/query reload)', () => {
  assert.equal(isAllowedNavigation('file:///C:/app/resources/pwa/index.html', PROD_POLICY), true)
  // a reload carrying a client route/query keeps the same pathname → still allowed
  assert.equal(
    isAllowedNavigation('file:///C:/app/resources/pwa/index.html#/history?tab=x', PROD_POLICY),
    true,
  )
  assert.equal(
    isAllowedNavigation('file:///C:/app/resources/pwa/evil.html', PROD_POLICY),
    false, // any OTHER file path is denied
  )
  assert.equal(isAllowedNavigation('file:///etc/passwd', PROD_POLICY), false)
  assert.equal(isAllowedNavigation('https://evil.example.com/', PROD_POLICY), false) // external
  assert.equal(isAllowedNavigation('http://localhost:5173/', PROD_POLICY), false) // dev origin off in prod
  assert.equal(isAllowedNavigation('not a url', PROD_POLICY), false)
})
