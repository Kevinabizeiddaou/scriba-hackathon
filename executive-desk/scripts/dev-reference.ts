/**
 * Runs the frontend over real HTTP against the reference server, in one command:
 *
 *   npm run dev:reference        app on http://localhost:5184, reference server on :8787
 *
 * This is the same code path the real backend will use (HttpExecutiveDesk, handshake, retries,
 * idempotency keys, response validation), with the scripted mock on the other end. The sidebar
 * still says "Mock data", because GET /meta reports a scripted agent.
 */
import react from '@vitejs/plugin-react';
import { createServer } from 'vite';
import { ReferenceServer } from '../src/api/reference/referenceServer';

const api = await ReferenceServer.start({ port: 8787, allowOrigin: 'http://localhost:5184', mock: { stepDelayMs: 600, seed: true } });

const vite = await createServer({
  configFile: false,
  plugins: [react()],
  server: { port: 5184, strictPort: true },
  define: {
    'import.meta.env.VITE_API_MODE': JSON.stringify('http'),
    'import.meta.env.VITE_API_BASE_URL': JSON.stringify(api.baseUrl),
  },
});
await vite.listen();

console.log(`Reference server (scripted): ${api.baseUrl}`);
console.log('Frontend over HTTP:         http://localhost:5184');

const stop = () => void Promise.all([vite.close(), api.stop()]).then(() => process.exit(0));
process.on('SIGINT', stop);
process.on('SIGTERM', stop);
