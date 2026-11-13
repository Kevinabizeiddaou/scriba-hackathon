#!/usr/bin/env node
/**
 * Refuses a commit that would carry a secret, a token store or a database dump.
 * Scans the files Git would commit (tracked + staged), never node_modules.
 *
 *   node scripts/check-no-secrets.mjs
 */
import { execFileSync } from 'node:child_process'
import { readFileSync, statSync } from 'node:fs'

const files = execFileSync('git', ['ls-files', '--cached', '--others', '--exclude-standard'], {
  encoding: 'utf8',
}).split('\n').filter(Boolean)

const FORBIDDEN_NAMES = [
  /(^|\/)\.env(\.(?!example$)[^/]*)?$/i,
  /(^|\/)tokens?\//i,
  /(^|\/)tokens?_[^/]*\.json$/i,
  /(^|\/)client_secret[^/]*\.json$/i,
  /\.(pem|key|p12|pfx|sqlite3?|dump)$/i,
  /\.sql\.gz$/i,
]

// Values, not names: a variable NAME such as GOOGLE_CLIENT_SECRET is fine in
// documentation; an assigned value is not.
const FORBIDDEN_CONTENT = [
  ['Google OAuth client secret', /GOCSPX-[A-Za-z0-9_-]{20,}/],
  ['Google refresh token', /\b1\/\/0[A-Za-z0-9_-]{30,}/],
  ['Google access token', /\bya29\.[A-Za-z0-9_-]{30,}/],
  ['OpenAI-style API key', /\bsk-[A-Za-z0-9_-]{24,}/],
  ['AWS access key id', /\bAKIA[0-9A-Z]{16}\b/],
  ['Stripe live key', /\b[sr]k_live_[A-Za-z0-9]{16,}/],
  ['private key block', /-----BEGIN [A-Z ]*PRIVATE KEY-----/],
  ['database URL with a password', /postgres(ql)?:\/\/[^\s:/@]+:[^\s@/]{6,}@(?!localhost|127\.0\.0\.1|db[:/])/i],
  ['assigned secret', /\b(CLIENT_SECRET|ENCRYPTION_KEY|SESSION_SECRET(_KEY)?|API_KEY|SIGNING_SECRET)\s*[=:]\s*["']?[A-Za-z0-9+/_=-]{16,}/],
]

const problems = []
for (const file of files) {
  if (FORBIDDEN_NAMES.some(pattern => pattern.test(file))) {
    problems.push(`${file}: file of this kind must not be committed`)
    continue
  }
  let size = 0
  try {
    size = statSync(file).size
  } catch {
    continue
  }
  if (size > 2_000_000 || /\.(png|jpe?g|gif|ico|woff2?|ttf|pdf)$/i.test(file)) continue
  if (file === 'scripts/check-no-secrets.mjs') continue
  const text = readFileSync(file, 'utf8')
  for (const [label, pattern] of FORBIDDEN_CONTENT) {
    if (pattern.test(text)) problems.push(`${file}: looks like a ${label}`)
  }
}

if (problems.length) {
  console.error('Refusing: possible secrets in files Git would commit:\n  ' + problems.join('\n  '))
  process.exit(1)
}
console.log(`No secrets found in ${files.length} file(s).`)
