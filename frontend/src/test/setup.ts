// Transferred unchanged from Scriba: Gmail/frontend/src/test/setup.ts @ 3ae3a2aa.
// Vitest test setup: jest-dom matchers + automatic RTL cleanup between tests.
import '@testing-library/jest-dom/vitest'
import { afterEach } from 'vitest'
import { cleanup } from '@testing-library/react'

afterEach(() => {
  cleanup()
})
