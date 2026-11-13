import { ArrowRight, CalendarClock, CalendarPlus, CalendarX, Mail, MapPin, Users, type LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';
import type { CalendarEvent, CalendarEventDraft, Participant, ProposedChange } from '../api/types';
import { fmtRange } from '../lib/time';

function Frame({ icon: Icon, verb, children }: { icon: LucideIcon; verb: string; children: ReactNode }) {
  return (
    <section className="overflow-hidden rounded-xl border border-line bg-sunken/70">
      <h3 className="flex items-center gap-2 border-b border-line bg-white/[0.03] px-3.5 py-2 text-[12px] font-semibold uppercase tracking-[0.06em] text-soft">
        <Icon aria-hidden className="h-3.5 w-3.5 text-accent" />
        {verb}
      </h3>
      <div className="space-y-2 px-3.5 py-3">{children}</div>
    </section>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex gap-3 text-[13px]">
      <span className="w-14 shrink-0 text-mute">{label}</span>
      <span className="min-w-0 flex-1 break-words text-ink">{children}</span>
    </div>
  );
}

function others(attendees: Participant[], principalEmail: string): string {
  const rest = attendees.filter((a) => a.email !== principalEmail);
  return rest.length ? rest.map((a) => a.name).join(', ') : 'Only you';
}

function EventFacts({ event, timeZone, principalEmail }: { event: CalendarEvent | CalendarEventDraft; timeZone: string; principalEmail: string }) {
  return (
    <>
      <p className="text-[14.5px] font-semibold text-ink">{event.title}</p>
      <p className="tabular-nums text-[13px] text-soft">{fmtRange(event.start, event.end, timeZone)}</p>
      <p className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[12.5px] text-soft">
        <span className="inline-flex items-center gap-1.5">
          <Users aria-hidden className="h-3.5 w-3.5 text-mute" />
          {others(event.attendees, principalEmail)}
        </span>
        {event.location && (
          <span className="inline-flex items-center gap-1.5">
            <MapPin aria-hidden className="h-3.5 w-3.5 text-mute" />
            {event.location}
          </span>
        )}
      </p>
    </>
  );
}

/** Shows exactly what the agent intends to do, in the form the recipient or the calendar will see it. */
export function ChangePreview({ change, timeZone, principalEmail }: { change: ProposedChange; timeZone: string; principalEmail: string }) {
  switch (change.type) {
    case 'email':
      return (
        <Frame icon={Mail} verb="Send this email">
          <Row label="To">{change.to.join(', ')}</Row>
          {change.cc.length > 0 && <Row label="Cc">{change.cc.join(', ')}</Row>}
          <Row label="Subject">{change.subject}</Row>
          <p className="whitespace-pre-wrap rounded-lg border border-line bg-bg/60 px-3 py-2.5 text-[13.5px] leading-[21px] text-ink">{change.bodyText}</p>
        </Frame>
      );
    case 'calendar_create':
      return (
        <Frame icon={CalendarPlus} verb="Create this event">
          <EventFacts event={change.event} timeZone={timeZone} principalEmail={principalEmail} />
          <p className="text-[12px] text-mute">Attendees receive a calendar invitation.</p>
        </Frame>
      );
    case 'calendar_update':
      return (
        <Frame icon={CalendarClock} verb="Move this event">
          <p className="text-[14.5px] font-semibold text-ink">{change.after.title}</p>
          <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1 tabular-nums text-[13px]">
            <span className="text-mute line-through decoration-white/30">{fmtRange(change.before.start, change.before.end, timeZone)}</span>
            <ArrowRight aria-label="moves to" className="h-3.5 w-3.5 text-accent" />
            <span className="font-semibold text-ink">{fmtRange(change.after.start, change.after.end, timeZone)}</span>
          </div>
          <p className="text-[12px] text-mute">The existing event is updated; attendees ({others(change.after.attendees, principalEmail)}) get an update, not a second invitation.</p>
        </Frame>
      );
    case 'calendar_cancel':
      return (
        <Frame icon={CalendarX} verb="Cancel this event">
          <EventFacts event={change.event} timeZone={timeZone} principalEmail={principalEmail} />
          <p className="text-[12px] text-mute">{change.notifyAttendees ? 'Attendees are notified of the cancellation.' : 'Attendees are not notified.'}</p>
        </Frame>
      );
  }
}
