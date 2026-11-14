// Vitest setup: jest-dom matchers. With `globals: true` (vite.config.ts) React Testing Library
// registers its own cleanup after each test, so none is declared here.
import '@testing-library/jest-dom/vitest'
import { configure } from '@testing-library/react'
// Tests install the mock themselves (setApi), and the data layer needs it registered to pair a
// mock API with the mock workspace.
import '../harness/mock/runtime'

// findBy* and waitFor give up after one second by default. The harness self-test and the
// scripted runs take longer than that on a busy machine, and a query that gives up early leaves
// its run finishing inside the next test.
configure({ asyncUtilTimeout: 15_000 })
