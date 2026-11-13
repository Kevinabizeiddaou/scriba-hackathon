import { lazy, Suspense } from 'react'
import { DESK_MODE } from './lib/mode'
import { LiveApp } from './live/LiveApp'

const DemoApp = lazy(() => import('./DemoApp'))

/**
 * One application. In live mode (the default) it sits behind Scriba's session and reads Scriba's
 * API. In demo mode it runs the in-memory mock, labelled as mock data on every screen. The two
 * are never mixed: live screens do not fall back to mock data when a request fails, and the live
 * bundle does not contain the mock.
 */
export default function App() {
  if (DESK_MODE === 'live') return <LiveApp />
  return (
    <Suspense fallback={<main className="grid h-full place-items-center text-[13px] text-soft" role="status">Loading the demo…</main>}>
      <DemoApp />
    </Suspense>
  )
}
