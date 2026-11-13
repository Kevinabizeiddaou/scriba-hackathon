import clsx from 'clsx';
import { AlertTriangle, CalendarDays, MapPin, ShieldCheck, Users, X } from 'lucide-react';
import { useState } from 'react';
import { getApi } from '../api';
import type { AgendaEvent } from '../api/workspace';
import { EmptyState, PageHeader, SkeletonRows } from '../components/ui';
import { SourceBadge, WorkspaceState, nowMs } from '../components/workspace';
import { hrefFor, navigate } from '../lib/router';
import { fmtDay, fmtRange, fmtTime, localParts } from '../lib/time';
import { useWorkspace } from '../lib/useResource';

const START_HOUR = 8;
const END_HOUR = 19;
const HOUR_PX = 54;

const minutesOf = (iso: string, tz: string) => {
  const [h, m] = localParts(iso, tz).time.split(':').map(Number);
  return h * 60 + m;
};

/** Monday to Friday of the week that contains `now`, as YYYY-MM-DD in the principal's zone. */
function weekDays(tz: string): string[] {
  const today = localParts(new Date(nowMs()).toISOString(), tz);
  const monday = Date.parse(`${today.date}T12:00:00Z`) - (today.weekday - 1) * 86_400_000;
  return Array.from({ length: 5 }, (_, i) => new Date(monday + i * 86_400_000).toISOString().slice(0, 10));
}

/** Puts overlapping events side by side: each gets a lane, and the day is as wide as its busiest moment. */
function layout(events: AgendaEvent[]): { event: AgendaEvent; lane: number; lanes: number }[] {
  const sorted = [...events].sort((a, b) => Date.parse(a.start) - Date.parse(b.start) || Date.parse(b.end) - Date.parse(a.end));
  const laneEnds: number[] = [];
  const placed = sorted.map((event) => {
    let lane = laneEnds.findIndex((end) => end <= Date.parse(event.start));
    if (lane < 0) lane = laneEnds.length;
    laneEnds[lane] = Date.parse(event.end);
    return { event, lane };
  });
  return placed.map((p) => ({ ...p, lanes: laneEnds.length }));
}

const blockStyle = (event: AgendaEvent) =>
  clsx(
    'border text-left transition-colors duration-150',
    event.kind === 'proposed'
      ? 'border-dashed border-warn/70 bg-warn/[0.08] text-warn hover:bg-warn/[0.14]'
      : event.provider === 'google'
        ? 'border-brand-400/50 bg-brand-500/40 text-ink hover:bg-brand-500/55'
        : 'border-info/40 bg-info/[0.16] text-ink hover:bg-info/[0.24]',
    event.conflictsWith.length > 0 && 'ring-2 ring-danger/80',
  );

function Legend() {
  return (
    <ul className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[12px] text-soft" aria-label="Legend">
      <li className="flex items-center gap-1.5">
        <span aria-hidden className="h-3 w-3 rounded-[4px] border border-brand-400/50 bg-brand-500/40" />
        Google Calendar
      </li>
      <li className="flex items-center gap-1.5">
        <span aria-hidden className="h-3 w-3 rounded-[4px] border border-info/40 bg-info/[0.16]" />
        Outlook Calendar
      </li>
      <li className="flex items-center gap-1.5">
        <span aria-hidden className="h-3 w-3 rounded-[4px] border border-dashed border-warn/70" />
        Proposed, not on a calendar yet
      </li>
      <li className="flex items-center gap-1.5">
        <span aria-hidden className="h-3 w-3 rounded-[4px] ring-2 ring-danger/80" />
        Conflict
      </li>
    </ul>
  );
}

function Preparation({ event, all, onClose }: { event: AgendaEvent; all: AgendaEvent[]; onClose: () => void }) {
  const tz = getApi().info.principal.timezone;
  const prep = useWorkspace((w) => w.getMeetingPrep(event.id), [event.id]);
  const emails = useWorkspace((w) => w.listEmails(), []);
  const tasks = useWorkspace((w) => w.listTasks(), []);
  const clashes = all.filter((e) => event.conflictsWith.includes(e.id));
  const others = event.attendees.filter((a) => a.email !== getApi().info.principal.email);

  return (
    <aside aria-label="Meeting preparation" className="card rise-in p-4 sm:p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="eyebrow">{event.kind === 'proposed' ? 'Proposed slot' : 'Meeting preparation'}</p>
          <h2 className="mt-1 text-[17px] font-semibold leading-6 text-ink">{event.title}</h2>
          <p className="mt-0.5 tabular-nums text-[13px] text-soft">{fmtRange(event.start, event.end, tz)}</p>
        </div>
        <button type="button" onClick={onClose} aria-label="Close preparation" className="tap inline-flex cursor-pointer items-center justify-center rounded-md p-1 text-mute hover:bg-white/[0.08] hover:text-ink">
          <X aria-hidden className="h-4 w-4" />
        </button>
      </div>
      <p className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[12.5px] text-soft">
        <SourceBadge source={event.provider} />
        <span>{event.calendar}</span>
        {event.location && (
          <span className="inline-flex items-center gap-1.5">
            <MapPin aria-hidden className="h-3.5 w-3.5 text-mute" />
            {event.location}
          </span>
        )}
        {others.length > 0 && (
          <span className="inline-flex items-center gap-1.5">
            <Users aria-hidden className="h-3.5 w-3.5 text-mute" />
            {others.map((a) => a.name).join(', ')}
          </span>
        )}
      </p>

      {clashes.length > 0 && (
        <p role="alert" className="mt-3 flex gap-2.5 rounded-xl border border-danger/30 bg-danger/[0.08] px-3.5 py-2.5 text-[13px] text-danger">
          <AlertTriangle aria-hidden className="mt-0.5 h-4 w-4 shrink-0" />
          <span>
            Overlaps {clashes.map((c) => `"${c.title}" (${c.calendar}, ${fmtTime(c.start, tz)} to ${fmtTime(c.end, tz)})`).join(' and ')}. The two are on different calendars, so neither calendar shows the clash on its own.
          </span>
        </p>
      )}

      {event.kind === 'proposed' ? (
        <div className="mt-3">
          <p className="text-[13px] text-soft">This time has been proposed by the secretary. It is not on any calendar until it is approved and, where it was offered to someone else, accepted.</p>
          {event.approvalId && (
            <a href={hrefFor('approvals', event.approvalId)} className="btn btn-primary mt-3">
              <ShieldCheck aria-hidden className="h-4 w-4" />
              Review the proposal
            </a>
          )}
        </div>
      ) : prep.loading ? (
        <div className="mt-3">
          <SkeletonRows rows={2} />
        </div>
      ) : prep.data ? (
        <div className="mt-3.5 space-y-3.5 text-[13px]">
          <p className="leading-[21px] text-ink">{prep.data.purpose}</p>
          {prep.data.attendees.length > 0 && (
            <div>
              <h3 className="eyebrow mb-1.5">Who is in the room</h3>
              <ul className="space-y-1.5">
                {prep.data.attendees.map(({ person, note }) => (
                  <li key={person.email}>
                    <span className="font-semibold text-ink">{person.name}</span>
                    <span className="block text-soft">{note}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {prep.data.talkingPoints.length > 0 && (
            <div>
              <h3 className="eyebrow mb-1.5">Talking points</h3>
              <ul className="list-disc space-y-1 pl-4 text-ink marker:text-mute">
                {prep.data.talkingPoints.map((point) => (
                  <li key={point}>{point}</li>
                ))}
              </ul>
            </div>
          )}
          {prep.data.relatedEmailIds.length > 0 && (
            <div>
              <h3 className="eyebrow mb-1.5">Related mail</h3>
              <ul className="space-y-1">
                {prep.data.relatedEmailIds.map((id) => {
                  const email = emails.data?.find((e) => e.id === id);
                  return email ? (
                    <li key={id}>
                      <a href={hrefFor('inbox', id)} className="tap inline-flex items-center font-medium text-accent hover:underline">
                        {email.from.name}: {email.subject}
                      </a>
                    </li>
                  ) : null;
                })}
              </ul>
            </div>
          )}
          {prep.data.openTaskIds.length > 0 && (
            <div>
              <h3 className="eyebrow mb-1.5">Open tasks</h3>
              <ul className="space-y-1 text-ink">
                {prep.data.openTaskIds.map((id) => {
                  const task = tasks.data?.find((t) => t.id === id);
                  return task ? <li key={id}>{task.title}</li> : null;
                })}
              </ul>
            </div>
          )}
          {prep.data.lastContact && <p className="text-mute">{prep.data.lastContact}</p>}
        </div>
      ) : null}
    </aside>
  );
}

export function CalendarPage({ eventId }: { eventId: string | null }) {
  const tz = getApi().info.principal.timezone;
  const agenda = useWorkspace((w) => w.listAgenda(), []);
  const days = weekDays(tz);
  const today = localParts(new Date(nowMs()).toISOString(), tz).date;
  const wide = typeof window !== 'undefined' && typeof window.matchMedia === 'function' ? window.matchMedia('(min-width: 768px)').matches : true;
  const [view, setView] = useState<'week' | 'day'>(wide ? 'week' : 'day');
  const [day, setDay] = useState(days.includes(today) ? today : days[0]);

  const events = agenda.data ?? [];
  const selected = events.find((e) => e.id === eventId) ?? null;
  const onDay = (date: string) => events.filter((e) => localParts(e.start, tz).date === date);
  const conflicts = events.filter((e) => e.kind === 'event' && e.conflictsWith.length > 0).length / 2;
  const hours = Array.from({ length: END_HOUR - START_HOUR }, (_, i) => START_HOUR + i);
  const select = (id: string | null) => navigate('calendar', id);

  return (
    <div>
      <PageHeader
        title="Calendar"
        subtitle="Google Calendar and Outlook Calendar together, with the slots the secretary has proposed and any clash between the two."
        actions={
          <div role="group" aria-label="Calendar view" className="inline-flex rounded-full border border-line bg-sunken/60 p-1">
            {(['week', 'day'] as const).map((v) => (
              <button key={v} type="button" aria-pressed={view === v} onClick={() => setView(v)} className={clsx('tap inline-flex h-8 cursor-pointer items-center rounded-full px-3.5 text-[13px] font-semibold capitalize transition-colors duration-150', view === v ? 'bg-brand-500/50 text-ink' : 'text-soft hover:text-ink')}>
                {v}
              </button>
            ))}
          </div>
        }
      />
      <div className="px-4 pb-12 sm:px-6 lg:px-8">
        <WorkspaceState error={agenda.error} onRetry={agenda.reload}>
          {agenda.loading ? (
            <SkeletonRows rows={6} />
          ) : (
            <div className={clsx('grid gap-5', selected && 'xl:grid-cols-[minmax(0,1fr)_380px]')}>
              <div className="min-w-0 space-y-3">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <Legend />
                  {conflicts > 0 && (
                    <p className="inline-flex items-center gap-1.5 text-[12.5px] font-semibold text-danger">
                      <AlertTriangle aria-hidden className="h-3.5 w-3.5" />
                      {conflicts} {conflicts === 1 ? 'conflict' : 'conflicts'} between calendars this week
                    </p>
                  )}
                </div>

                {view === 'week' ? (
                  <div className="card relative overflow-x-auto" role="region" aria-label="Week view" tabIndex={0}>
                    <div className="min-w-[760px]">
                      <div className="grid grid-cols-[52px_repeat(5,minmax(0,1fr))] border-b border-line">
                        <span />
                        {days.map((date) => (
                          <div key={date} className={clsx('border-l border-line px-2.5 py-2 text-[12.5px] font-semibold', date === today ? 'text-accent' : 'text-soft')}>
                            {fmtDay(`${date}T12:00:00Z`, 'UTC')}
                            {date === today && <span className="ml-1.5 font-normal text-mute">today</span>}
                          </div>
                        ))}
                      </div>
                      <div className="grid grid-cols-[52px_repeat(5,minmax(0,1fr))]">
                        <div aria-hidden>
                          {hours.map((hour) => (
                            <div key={hour} style={{ height: HOUR_PX }} className="pr-2 text-right text-[11px] tabular-nums leading-none text-mute">
                              <span className="relative -top-1.5">{String(hour).padStart(2, '0')}:00</span>
                            </div>
                          ))}
                        </div>
                        {days.map((date) => (
                          <div key={date} className="relative border-l border-line" style={{ height: hours.length * HOUR_PX }}>
                            {hours.map((hour) => (
                              <div key={hour} aria-hidden style={{ top: (hour - START_HOUR) * HOUR_PX }} className="absolute inset-x-0 border-t border-line" />
                            ))}
                            {layout(onDay(date)).map(({ event, lane, lanes }) => {
                              const top = ((minutesOf(event.start, tz) - START_HOUR * 60) / 60) * HOUR_PX;
                              const height = Math.max(((Date.parse(event.end) - Date.parse(event.start)) / 3_600_000) * HOUR_PX, 24);
                              return (
                                <button
                                  key={event.id}
                                  type="button"
                                  onClick={() => select(event.id)}
                                  aria-pressed={event.id === eventId}
                                  aria-label={`${event.title}, ${fmtRange(event.start, event.end, tz)}, ${event.kind === 'proposed' ? 'proposed' : event.calendar}${event.conflictsWith.length ? ', in conflict' : ''}`}
                                  style={{ top: top + 1, height: height - 2, left: `calc(${(lane / lanes) * 100}% + 2px)`, width: `calc(${100 / lanes}% - 4px)` }}
                                  className={clsx('absolute cursor-pointer overflow-hidden rounded-lg px-1.5 py-1', blockStyle(event), event.id === eventId && 'outline outline-2 outline-accent')}
                                >
                                  <span className="block truncate text-[11.5px] font-semibold leading-4">{event.title}</span>
                                  <span className="block truncate text-[10.5px] tabular-nums leading-4 opacity-80">
                                    {fmtTime(event.start, tz)} to {fmtTime(event.end, tz)}
                                  </span>
                                </button>
                              );
                            })}
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="space-y-3">
                    <div role="group" aria-label="Day" className="flex gap-1.5 overflow-x-auto">
                      {days.map((date) => (
                        <button key={date} type="button" aria-pressed={day === date} onClick={() => setDay(date)} className={clsx('tap inline-flex h-9 shrink-0 cursor-pointer items-center rounded-full px-3.5 text-[13px] font-semibold transition-colors duration-150', day === date ? 'bg-brand-500/40 text-ink' : 'text-soft hover:bg-white/[0.06]')}>
                          {fmtDay(`${date}T12:00:00Z`, 'UTC')}
                        </button>
                      ))}
                    </div>
                    {onDay(day).length === 0 ? (
                      <EmptyState icon={CalendarDays} title="Nothing scheduled">
                        No events or proposed slots on this day.
                      </EmptyState>
                    ) : (
                      <ol className="space-y-2" aria-label="Agenda">
                        {onDay(day).map((event) => (
                          <li key={event.id}>
                            <button type="button" onClick={() => select(event.id)} aria-pressed={event.id === eventId} className={clsx('flex w-full cursor-pointer items-start gap-3 rounded-xl px-3.5 py-3', blockStyle(event))}>
                              <span className="w-[92px] shrink-0 tabular-nums text-[12.5px] opacity-90">
                                {fmtTime(event.start, tz)} to {fmtTime(event.end, tz)}
                              </span>
                              <span className="min-w-0 flex-1">
                                <span className="block text-[14px] font-semibold">{event.title}</span>
                                <span className="mt-0.5 flex flex-wrap items-center gap-x-3 text-[12px]">
                                  {event.kind === 'proposed' ? <span className="font-semibold">Proposed</span> : <SourceBadge source={event.provider} />}
                                  {event.conflictsWith.length > 0 && (
                                    <span className="inline-flex items-center gap-1 font-semibold text-danger">
                                      <AlertTriangle aria-hidden className="h-3 w-3" />
                                      Conflict
                                    </span>
                                  )}
                                </span>
                              </span>
                            </button>
                          </li>
                        ))}
                      </ol>
                    )}
                  </div>
                )}
              </div>

              {selected && <Preparation key={selected.id} event={selected} all={events} onClose={() => select(null)} />}
            </div>
          )}
        </WorkspaceState>
      </div>
    </div>
  );
}
