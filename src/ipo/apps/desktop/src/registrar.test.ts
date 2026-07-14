// Security test for the registrar host allowlist (v3 V3-6) — the one place a data-plane value drives
// a real-world action (opening a page the user may type their PAN into). A URL outside the allowlist
// MUST fail to open. Electron-free, run via `node --test` (see package.json).

import assert from 'node:assert/strict'
import { test } from 'node:test'
import { isAllowedRegistrarUrl } from './registrar'

test('allows the pinned registrar hosts and their subdomains', () => {
  for (const url of [
    'https://in.mpms.mufg.com/', // MUFG Intime (subdomain)
    'https://mpms.mufg.com/', // apex
    'https://www.bigshareonline.com/ipo/allotment',
    'https://kosmic.kfintech.com/', // KFin allotment subdomain
    'https://kfintech.com/',
    'https://linkintime.co.in/',
    'https://www.cameoindia.com/',
  ]) {
    assert.equal(isAllowedRegistrarUrl(url), true, url)
  }
})

test('refuses an unknown host even over https (the poisoned-cache case)', () => {
  for (const url of [
    'https://evil.example.com/phish', // arbitrary attacker page
    'https://kfintech.com.evil.com/', // look-alike: registrar domain as a left-label
    'https://notkfintech.com/', // look-alike: not a subdomain boundary
    'https://mufg.com/', // parent bank domain, not the pinned registrar host
  ]) {
    assert.equal(isAllowedRegistrarUrl(url), false, url)
  }
})

test('refuses non-https and non-URLs', () => {
  for (const url of [
    'http://in.mpms.mufg.com/', // downgraded scheme
    'javascript:alert(1)',
    'file:///etc/passwd',
    'not a url',
    '',
  ]) {
    assert.equal(isAllowedRegistrarUrl(url), false, url)
  }
})
