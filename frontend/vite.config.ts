import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// The Scriba API accepts credentialed requests from the local development
// origin http://localhost:5173 (and 127.0.0.1:5173). Requests from any other
// port are refused, so the port is fixed, not a preference.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, strictPort: true },
  preview: { port: 5173, strictPort: true },
  test: {
    environment: 'jsdom',
    // Tests run at the Desk's real dev origin, so apiBase resolves exactly as
    // it does in the browser (localhost:5173 -> API on localhost:8000).
    environmentOptions: { jsdom: { url: 'http://localhost:5173' } },
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
  },
})
