#!/usr/bin/env node
/**
 * The app is started only through Docker (`docker compose build`, then `docker compose up -d`
 * from the repository root). The frontend image sets DESK_IN_DOCKER=1; anywhere else the dev
 * and preview servers refuse to start, so nobody ends up on a half-configured local setup
 * (no API, wrong port, Windows node_modules).
 *
 * Tests, typecheck, build and the evaluation CLI still run on the host.
 */
if (process.env.DESK_IN_DOCKER !== '1') {
  console.error(
    [
      '',
      'The Scriba Executive Desk runs in Docker only. From the repository root:',
      '',
      '  docker compose build',
      '  docker compose up -d        http://localhost:5173',
      '',
      'See "Run it" in README.md.',
      '',
    ].join('\n'),
  )
  process.exit(1)
}
