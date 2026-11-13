/**
 * Starts the reference server: the contract served over real HTTP by the scripted mock.
 *
 *   npm run contract:server                     http://127.0.0.1:8787/api/executive-desk/v1
 *   npm run contract:server -- --port 9000
 *   DESK_SESSION=some-test-value npm run contract:server -- --session-env DESK_SESSION
 *
 * Use it to see the contract on the wire, or to run the frontend and the evaluation runner
 * over HTTP before the real backend exists:
 *
 *   VITE_API_MODE=http VITE_API_BASE_URL=http://127.0.0.1:8787/api/executive-desk/v1 npm run dev
 *   npm run eval -- --base-url http://127.0.0.1:8787/api/executive-desk/v1
 *
 * It is not a backend. GET /meta says agent: "scripted", so clients label everything simulated.
 */
import { ReferenceServer } from '../src/harness/reference/referenceServer';

const argv = process.argv.slice(2);
const option = (name: string) => {
  const index = argv.indexOf(`--${name}`);
  return index >= 0 ? argv[index + 1] : undefined;
};

const sessionEnv = option('session-env');
const session = sessionEnv ? process.env[sessionEnv] : undefined;
if (sessionEnv && !session) {
  console.error(`Environment variable ${sessionEnv} is not set.`);
  process.exit(2);
}

const server = await ReferenceServer.start({
  port: Number(option('port') ?? 8787),
  session: session ?? null,
  // Slow enough to watch a run progress in the UI.
  mock: { stepDelayMs: Number(option('step-delay') ?? 600), seed: true },
});

console.log(`Executive Desk reference server (scripted, simulated) listening on ${server.baseUrl}`);
console.log(session ? `Session cookie required: desk_session=<value of ${sessionEnv}>.` : 'No authentication. Pass --session-env NAME to require a session cookie.');
console.log('Try: curl ' + server.baseUrl + '/meta');

const stop = () => void server.stop().then(() => process.exit(0));
process.on('SIGINT', stop);
process.on('SIGTERM', stop);
