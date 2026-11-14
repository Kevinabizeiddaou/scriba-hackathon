import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// The Scriba API accepts credentialed requests from the local development
// origin http://localhost:5173 (and 127.0.0.1:5173). Requests from any other
// port are refused, so the port is fixed, not a preference.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, strictPort: true },
  preview: { port: 5173, strictPort: true },
  build: {
    // React and the data libraries change far less often than the Desk does, so they are kept in
    // their own files: a new Desk build does not make a returning user download them again.
    rolldownOptions: {
      output: {
        advancedChunks: {
          groups: [
            { name: 'react', test: /node_modules[\\/](react|react-dom|scheduler)[\\/]/ },
            { name: 'data', test: /node_modules[\\/](@tanstack|axios)[\\/]/ },
          ],
        },
      },
    },
  },
  test: {
    // The transplanted harness tests use describe/it/expect as globals.
    globals: true,
    environment: 'jsdom',
    // Tests run at the Desk's real dev origin, so apiBase resolves exactly as
    // it does in the browser (localhost:5173 -> API on localhost:8000).
    environmentOptions: { jsdom: { url: 'http://localhost:5173' } },
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
    css: false,
    // The UI suites drive whole screens through jsdom; on a busy machine 5 s is not enough.
    testTimeout: 30_000,
    hookTimeout: 30_000,
  },
})
