import { Desk } from './Desk'
import { DESK_MODE } from './lib/mode'
import { LiveApp } from './live/LiveApp'

/**
 * One application. In live mode (the default) it sits behind Scriba's session and reads Scriba's
 * API. In demo mode it runs the in-memory mock, labelled as mock data on every screen. The two
 * are never mixed: live screens do not fall back to mock data when a request fails.
 */
export default function App() {
  return DESK_MODE === 'live' ? <LiveApp /> : <Desk />
}
