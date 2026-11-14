/**
 * The scheduling workspace: when the executive is free, across every connected Google and
 * Outlook calendar, and whether one specific time works.
 *
 * It reads GET /desk/availability and POST /desk/slots/check and writes nothing. Two rules shape
 * the screen: a free time is offered only when every connected calendar was read, and a time
 * whose check came back unknown is never shown as free.
 */
import clsx from 'clsx'
import { ArrowLeft, CalendarSearch, CircleCheck, CircleHelp, CircleX, MessageSquareText, RefreshCw, ShieldAlert } from 'lucide-react'
import { useEffect, useState, type FormEvent } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { getErrorMessage } from '../api/client'
import { checkDeskSlot, fetchDeskAvailability, type BusyInterval, type CalendarRead, type DeskSlotCheck } from '../api/desk'
import { Button, ErrorNote, PageHeader, SkeletonRows } from '../components/ui'
import { SourceBadge } from '../components/workspace'
import { getApi } from '../harness'
import { hrefFor } from '../lib/router'
import { fmtDay, fmtRange, fmtTime, isInstant, localParts } from '../lib/time'
import { openChatWithPrompt } from './LiveChatPage'
import { INCOMPLETE_REASON, byDay, calendarProblem, localEnd, offeredSlots, rangeFor, slotVerdict, weekdayNames } from './scheduling'
import { useRequiredLiveSession } from './session'

const DAY_CHOICES = [3, 5, 7, 14] as const
const LENGTH_CHOICES = [15, 30, 45, 60, 90] as const

function Calendars({ calendars }: { calendars: CalendarRead[] }) {
  if (calendars.length === 0) return <p className="text-[12.5px] text-mute">No calendar is connected.</p>
  return (
    <ul className="space-y-1.5 text-[12.5px]" aria-label="Calendars read">
      {calendars.map(calendar => {
        const problem = calendarProblem(calendar)
        return (
          <li key={`${calendar.provider}:${calendar.account}`} className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
            <SourceBadge source={calendar.provider} />{' '}
            <span className="break-all text-ink">{calendar.account}</span>{' '}
            {problem ? (
              <span className="font-semibold text-warn">{problem}: availability unknown</span>
            ) : (
              <span className="text-ok">read, {calendar.busy_count} busy period{calendar.busy_count === 1 ? '' : 's'}</span>
            )}
          </li>
        )
      })}
    </ul>
  )
}

function Busy({ interval, tz }: { interval: BusyInterval; tz: string }) {
  return (
    <li className="flex flex-wrap items-baseline gap-x-2 text-[12.5px]">
      <span className="w-[108px] shrink-0 tabular-nums text-soft">{fmtTime(interval.start, tz)} to {fmtTime(interval.end, tz)}</span>{' '}
      <span className="min-w-0 flex-1 text-ink">{interval.title ?? 'Busy'}</span>{' '}
      <SourceBadge source={interval.provider} />{' '}
      <span className="break-all text-mute">{interval.account}</span>
    </li>
  )
}

function CheckResult({ check }: { check: DeskSlotCheck }) {
  const tz = check.timezone
  const verdict = slotVerdict(check)
  const style = {
    free: { icon: CircleCheck, box: 'border-ok/30 bg-ok/[0.07]', text: 'text-ok', title: 'Free on every connected calendar' },
    conflict: { icon: CircleX, box: 'border-danger/30 bg-danger/[0.07]', text: 'text-danger', title: 'Not free: it collides with an existing commitment' },
    unknown: { icon: CircleHelp, box: 'border-warn/35 bg-warn/[0.08]', text: 'text-warn', title: 'Unknown: a calendar could not be read' },
  }[verdict]
  return (
    <div role="status" aria-label="Result of the check" className={clsx('rounded-xl border px-3.5 py-3', style.box)}>
      <p className={clsx('flex items-center gap-2 text-[13.5px] font-semibold', style.text)}>
        <style.icon aria-hidden className="h-4 w-4 shrink-0" />
        {style.title}
      </p>
      <p className="mt-1 text-[12.5px] tabular-nums text-ink">
        {isInstant(check.slot.start) && isInstant(check.slot.end) ? fmtRange(check.slot.start, check.slot.end, tz) : `${check.slot.start} to ${check.slot.end}`} <span className="text-mute">({tz})</span>
      </p>
      {verdict === 'unknown' && <p className="mt-1.5 text-[12.5px] text-soft">No conflict was found in the calendars that answered, but that is not the same as free. Do not confirm this time until the calendar below can be read.</p>}
      {check.conflicts.length > 0 && (
        <ul className="mt-2 space-y-1" aria-label="Conflicts">
          {check.conflicts.map((conflict, index) => <Busy key={index} interval={conflict} tz={tz} />)}
        </ul>
      )}
      {!check.within_working_hours && <p className="mt-1.5 text-[12.5px] text-warn">This is outside your working hours.</p>}
      {check.buffer_minutes > 0 && <p className="mt-1.5 text-[12px] text-mute">Checked with {check.buffer_minutes} minutes kept clear on each side.</p>}
      {check.calendars.some(calendar => !calendar.ok) && (
        <div className="mt-2">
          <Calendars calendars={check.calendars} />
        </div>
      )}
    </div>
  )
}

export function LiveSchedulingPage() {
  const session = useRequiredLiveSession()
  const principalZone = getApi().info.principal.timezone
  const today = localParts(new Date().toISOString(), principalZone).date
  const [from, setFrom] = useState(today)
  const [days, setDays] = useState<number>(5)
  const [length, setLength] = useState<number | null>(null)
  const [checkStart, setCheckStart] = useState('')
  const [checkLength, setCheckLength] = useState(30)

  const range = rangeFor(from, days)
  const availability = useQuery({
    queryKey: ['desk', 'availability', range.start, range.end, length],
    queryFn: () => fetchDeskAvailability({ ...range, duration_minutes: length ?? undefined, max_slots: 20 }),
    enabled: session.overlay === 'ok' && /^\d{4}-\d{2}-\d{2}$/.test(from),
  })
  const check = useMutation({ mutationFn: (body: { start: string; end: string }) => checkDeskSlot(body) })

  const data = availability.data
  const tz = data?.timezone ?? principalZone
  useEffect(() => {
    session.desk.setTimeZone(data?.timezone)
  }, [data?.timezone, session.desk])

  const slots = data ? offeredSlots(data) : []
  const dayOf = (iso: string) => fmtDay(iso, tz)
  const checkEnd = localEnd(checkStart, checkLength)

  function submitCheck(event: FormEvent) {
    event.preventDefault()
    if (!checkEnd) return
    // No offset: the backend reads the time in the user's Scriba time zone.
    check.mutate({ start: `${checkStart}:00`.slice(0, 19), end: `${checkEnd}:00` })
  }

  function pick(slot: { start: string; end: string }) {
    const local = localParts(slot.start, tz)
    setCheckStart(`${local.date}T${local.time}`)
    setCheckLength(Math.max(15, Math.round((Date.parse(slot.end) - Date.parse(slot.start)) / 60_000)))
    check.reset()
  }

  return (
    <div>
      <div className="px-4 pt-5 sm:px-6 lg:px-8">
        <a href={hrefFor('calendar')} className="tap inline-flex items-center gap-1.5 text-[13px] font-medium text-accent hover:underline">
          <ArrowLeft aria-hidden className="h-4 w-4" />
          Calendar
        </a>
      </div>
      <PageHeader
        title="Find a time"
        subtitle="When you are free across every connected Google and Outlook calendar. This reads calendars; it books nothing."
        actions={<Button icon={RefreshCw} onClick={() => void availability.refetch()} busy={availability.isFetching}>Read calendars again</Button>}
      />

      <div className="grid gap-5 px-4 pb-12 sm:px-6 lg:grid-cols-[minmax(0,1fr)_340px] lg:px-8">
        <div className="min-w-0 space-y-5">
          <form className="card flex flex-wrap items-end gap-3 p-4" aria-label="Range" onSubmit={event => event.preventDefault()}>
            <label className="block text-[12px] font-medium text-soft">
              From
              <input type="date" value={from} onChange={event => setFrom(event.target.value)} className="field mt-1 block h-10 w-[170px]" />
            </label>
            <label className="block text-[12px] font-medium text-soft">
              Days to look at
              <select value={days} onChange={event => setDays(Number(event.target.value))} className="field mt-1 block h-10 w-[120px]">
                {DAY_CHOICES.map(choice => <option key={choice} value={choice} className="bg-surface">{choice} days</option>)}
              </select>
            </label>
            <label className="block text-[12px] font-medium text-soft">
              Meeting length
              <select value={length ?? ''} onChange={event => setLength(event.target.value ? Number(event.target.value) : null)} className="field mt-1 block h-10 w-[170px]">
                <option value="" className="bg-surface">Your Scriba default</option>
                {LENGTH_CHOICES.map(choice => <option key={choice} value={choice} className="bg-surface">{choice} minutes</option>)}
              </select>
            </label>
          </form>

          {session.overlay !== 'ok' && session.overlay !== 'checking' && (
            <p role="alert" className="rounded-xl border border-warn/30 bg-warn/[0.08] px-3.5 py-3 text-[13px] text-warn">This backend does not have the Desk overlay, so availability across calendars cannot be read.</p>
          )}
          {availability.isPending && session.overlay === 'ok' && <SkeletonRows rows={4} />}
          {availability.isError && <ErrorNote error={new Error(`Availability could not be read: ${getErrorMessage(availability.error)}`)} onRetry={() => void availability.refetch()} />}

          {data && (
            <>
              {!data.complete && (
                <section role="alert" aria-label="Availability is not known" className="card space-y-2 border-warn/40 p-4 sm:p-5">
                  <p className="flex items-center gap-2 text-[14.5px] font-semibold text-warn">
                    <ShieldAlert aria-hidden className="h-4 w-4 shrink-0" />
                    {(data.reason && INCOMPLETE_REASON[data.reason]?.title) || 'Availability is not known'}
                  </p>
                  <p className="text-[13px] leading-[20px] text-soft">{(data.reason && INCOMPLETE_REASON[data.reason]?.detail) || 'No free time is offered until every connected calendar can be read.'}</p>
                </section>
              )}

              <section aria-label="Free times" className="card space-y-3 p-4 sm:p-5">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <h2 className="text-[14.5px] font-semibold text-ink">Free times</h2>
                  <p className="text-[12px] text-mute">{data.duration_minutes} minutes{data.buffer_minutes > 0 ? `, ${data.buffer_minutes} minutes clear on each side` : ''}, inside working hours</p>
                </div>
                {slots.length > 0 ? (
                  <div className="space-y-3">
                    {byDay(slots, dayOf).map(group => (
                      <div key={group.day}>
                        <p className="eyebrow mb-1.5">{group.day}</p>
                        <ul className="flex flex-wrap gap-1.5" aria-label={`Free times on ${group.day}`}>
                          {group.items.map(slot => (
                            <li key={slot.start}>
                              <button type="button" onClick={() => pick(slot)} className="tap inline-flex h-9 cursor-pointer items-center rounded-full border border-ok/30 bg-ok/[0.07] px-3 text-[12.5px] font-semibold tabular-nums text-ok transition-colors duration-150 hover:bg-ok/[0.14]" aria-label={`Use ${fmtRange(slot.start, slot.end, tz)}`}>
                                {fmtTime(slot.start, tz)} to {fmtTime(slot.end, tz)}
                              </button>
                            </li>
                          ))}
                        </ul>
                      </div>
                    ))}
                    <p className="text-[12px] text-mute">Verified against every connected calendar when this page was read. Choose one to check it again before you offer it.</p>
                  </div>
                ) : data.complete ? (
                  <p className="text-[13px] text-soft">No free time of this length inside your working hours in this range. Try more days or a shorter meeting.</p>
                ) : (
                  <p className="text-[13px] text-soft">None offered. A time is offered only when every connected calendar was read.</p>
                )}
              </section>

              {data.existing_conflicts.length > 0 && (
                <section aria-label="Existing conflicts" className="card space-y-2 border-danger/30 p-4 sm:p-5">
                  <h2 className="text-[14.5px] font-semibold text-danger">Already double-booked ({data.existing_conflicts.length})</h2>
                  <ul className="space-y-2.5">
                    {data.existing_conflicts.map((conflict, index) => (
                      <li key={index}>
                        <p className="text-[12.5px] font-semibold tabular-nums text-ink">{fmtRange(conflict.start, conflict.end, tz)}</p>
                        <ul className="mt-1 space-y-0.5">{conflict.between.map((interval, i) => <Busy key={i} interval={interval} tz={tz} />)}</ul>
                      </li>
                    ))}
                  </ul>
                </section>
              )}

              <section aria-label="Busy time" className="card space-y-3 p-4 sm:p-5">
                <h2 className="text-[14.5px] font-semibold text-ink">Busy time ({data.busy.length})</h2>
                {data.busy.length === 0 ? (
                  <p className="text-[13px] text-soft">{data.complete ? 'Nothing on any calendar in this range.' : 'Nothing was read. That does not mean the calendars are empty.'}</p>
                ) : (
                  byDay(data.busy, dayOf).map(group => (
                    <div key={group.day}>
                      <p className="eyebrow mb-1">{group.day}</p>
                      <ul className="space-y-1">{group.items.map((interval, index) => <Busy key={index} interval={interval} tz={tz} />)}</ul>
                    </div>
                  ))
                )}
                <p className="text-[12px] text-mute">Google reports busy time without titles; Outlook gives them.</p>
              </section>
            </>
          )}
        </div>

        <aside className="space-y-4" aria-label="Check and settings">
          <form onSubmit={submitCheck} className="card space-y-3 p-4" aria-label="Check one time">
            <h2 className="text-[14.5px] font-semibold text-ink">Check one time</h2>
            <label className="block text-[12px] font-medium text-soft">
              Start ({tz})
              <input type="datetime-local" required value={checkStart} onChange={event => { setCheckStart(event.target.value); check.reset() }} className="field mt-1 block h-10 w-full" />
            </label>
            <label className="block text-[12px] font-medium text-soft">
              Length
              <select value={checkLength} onChange={event => { setCheckLength(Number(event.target.value)); check.reset() }} className="field mt-1 block h-10 w-full">
                {[...new Set([...LENGTH_CHOICES, checkLength])].sort((a, b) => a - b).map(choice => <option key={choice} value={choice} className="bg-surface">{choice} minutes</option>)}
              </select>
            </label>
            <Button type="submit" variant="primary" icon={CalendarSearch} busy={check.isPending} disabled={!checkEnd} className="w-full">Check this time</Button>
            {check.isError && <p role="alert" className="text-[12.5px] text-danger">The time could not be checked: {getErrorMessage(check.error)}. That is not an answer about the time.</p>}
            {check.data && <CheckResult check={check.data} />}
            {check.data && slotVerdict(check.data) === 'free' && (
              <button
                type="button"
                onClick={() => openChatWithPrompt(`Book a meeting on ${fmtRange(check.data!.slot.start, check.data!.slot.end, check.data!.timezone)} (${check.data!.timezone}). `)}
                className="btn btn-secondary w-full"
              >
                <MessageSquareText aria-hidden className="h-4 w-4" />
                Take this time to the secretary chat
              </button>
            )}
            <p className="text-[12px] text-mute">Checking reads calendars only. Booking is proposed in chat and needs your approval; the time is checked again at that point.</p>
          </form>

          {data && (
            <section className="card space-y-3 p-4" aria-label="How this was read">
              <h2 className="eyebrow">How this was read</h2>
              <dl className="space-y-2 text-[12.5px]">
                <div>
                  <dt className="text-mute">Time zone</dt>
                  <dd className="text-ink">{data.timezone}</dd>
                </div>
                <div>
                  <dt className="text-mute">Working hours</dt>
                  <dd className="text-ink">{data.working_hours.start} to {data.working_hours.end}, {weekdayNames(data.working_hours.weekdays)}</dd>
                </div>
                <div>
                  <dt className="text-mute">Range</dt>
                  <dd className="tabular-nums text-ink">{fmtDay(data.range.start, tz)} to {fmtDay(new Date(Date.parse(data.range.end) - 1).toISOString(), tz)}</dd>
                </div>
              </dl>
              <div>
                <p className="mb-1 text-[12.5px] text-mute">Calendars</p>
                <Calendars calendars={data.calendars} />
              </div>
              <p className="text-[12px] text-mute">These come from your Scriba preferences and connections. Change them in Scriba.</p>
            </section>
          )}
        </aside>
      </div>
    </div>
  )
}
