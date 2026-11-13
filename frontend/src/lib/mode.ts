/**
 * Which data the Desk runs on. One switch, read in one place.
 *
 *   live  (default)  Scriba's API, through the session cookie. A failed request is shown as a
 *                    failure; nothing falls back to mock data.
 *   demo             The in-memory mock with fictional people: `npm run dev:demo`, or
 *                    VITE_DESK_MODE=demo. Labelled as mock data on every screen.
 *
 *   contract         VITE_API_MODE=http: the predecessor's contract-v1 HTTP adapter, which the
 *                    reference server (npm run dev:reference) and the evaluation CLI speak. No
 *                    Scriba backend serves that contract.
 *
 * VITE_API_MODE=mock is the predecessor's name for demo and is still accepted.
 */
export type DeskMode = 'live' | 'demo' | 'contract';

export function deskModeFrom(env: Record<string, string | undefined>): DeskMode {
  // `vite --mode demo` (npm run dev:demo) sets MODE; no env file is involved.
  if (env.MODE === 'demo' || env.VITE_DESK_MODE === 'demo' || env.VITE_API_MODE === 'mock') return 'demo';
  if (env.VITE_API_MODE === 'http') return 'contract';
  return 'live';
}

export const DESK_MODE: DeskMode = deskModeFrom(import.meta.env as Record<string, string | undefined>);
