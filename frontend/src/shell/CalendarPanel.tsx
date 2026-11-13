import { useQueries } from '@tanstack/react-query'
import { getErrorMessage } from '../api/client'
import { fetchCalendarEvents } from '../api/scriba'
import type { CalendarEntry, CalendarProvider } from '../api/contract'
import type { Capability, CapabilityId } from '../lib/connections'

const CALENDARS: ReadonlyArray<{ provider: CalendarProvider; capability: CapabilityId; label: string }> = [
  { provider: 'google', capability: 'google_calendar', label: 'Google Calendar' },
  { provider: 'outlook', capability: 'outlook_calendar', label: 'Outlook Calendar' },
]

/**
 * Read-only in Stage 1: one GET /calendar/events per connected calendar,
 * shown as a single list ordered by start time. Scriba serves these from its
 * synced copy of the calendar, so a just-created event appears after a sync.
 */
export function CalendarPanel({ capabilities }: { capabilities: Capability[] }) {
  const usable = CALENDARS.filter(
    item => capabilities.find(c => c.id === item.capability)?.state === 'connected',
  )
  const results = useQueries({
    queries: usable.map(item => ({
      queryKey: ['desk-calendar', item.provider],
      queryFn: () => fetchCalendarEvents(item.provider),
    })),
  })

  if (usable.length === 0) {
    return (
      <section aria-labelledby="calendar-heading">
        <h2 id="calendar-heading" className="text-xl font-semibold">Calendar</h2>
        <p className="text-sm mt-2">Connect Google Calendar or Outlook Calendar to see events here.</p>
      </section>
    )
  }

  const entries: Array<CalendarEntry & { source: string }> = results
    .flatMap((result, index) =>
      (result.data?.meetings ?? []).map(entry => ({ ...entry, source: usable[index].label })),
    )
    .sort((a, b) => String(a.start_time ?? '').localeCompare(String(b.start_time ?? '')))
  const loading = results.some(result => result.isPending)
  const failed = results.find(result => result.isError)

  return (
    <section aria-labelledby="calendar-heading" className="space-y-3">
      <h2 id="calendar-heading" className="text-xl font-semibold">Calendar</h2>
      <p className="text-sm opacity-80">Showing: {usable.map(item => item.label).join(' and ')}</p>
      {loading ? <p role="status" className="text-sm">Loading events…</p> : null}
      {failed ? (
        <p role="alert" className="text-sm">Could not load a calendar: {getErrorMessage(failed.error)}</p>
      ) : null}
      {!loading && !failed && entries.length === 0 ? (
        <p className="text-sm">No events in the current range.</p>
      ) : null}
      <ul className="space-y-2">
        {entries.map(entry => (
          <li key={`${entry.source}:${entry.key}`} className="card p-3">
            <strong>{entry.title || '(untitled event)'}</strong>
            <p className="text-sm opacity-80">
              {entry.start_time ? new Date(entry.start_time).toLocaleString() : 'No start time'}
              {entry.end_time ? ` to ${new Date(entry.end_time).toLocaleTimeString()}` : ''}
            </p>
            <p className="text-xs opacity-60">{entry.source}</p>
          </li>
        ))}
      </ul>
    </section>
  )
}
