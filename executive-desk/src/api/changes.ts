/** Helpers that relate a ProposedChange (what a human approves) to the tool call that carries it out. */
import type { ProposedChange } from './types';
import { fmtRange } from '../lib/time';

/** The AgentAction.input a tool call receives when it carries out this change. */
export function inputForChange(change: ProposedChange): Record<string, unknown> {
  switch (change.type) {
    case 'email':
      return {
        to: change.to,
        cc: change.cc,
        subject: change.subject,
        bodyText: change.bodyText,
        threadId: change.threadId,
        proposedSlots: change.proposedSlots,
      };
    case 'calendar_create':
      return { ...change.event, attendees: change.event.attendees.map((a) => a.email) };
    case 'calendar_update':
      return { eventId: change.eventId, ...change.after, attendees: change.after.attendees.map((a) => a.email) };
    case 'calendar_cancel':
      return { eventId: change.eventId, notifyAttendees: change.notifyAttendees };
  }
}

export function summaryForChange(change: ProposedChange, tense: 'past' | 'future' = 'past'): string {
  const past = tense === 'past';
  switch (change.type) {
    case 'email':
      return `${past ? 'Sent' : 'Send'} "${change.subject}" to ${change.to.join(', ')}`;
    case 'calendar_create':
      return `${past ? 'Created' : 'Create'} "${change.event.title}" on ${fmtRange(change.event.start, change.event.end, change.event.timezone)}`;
    case 'calendar_update':
      return `${past ? 'Moved' : 'Move'} "${change.after.title}" to ${fmtRange(change.after.start, change.after.end, change.after.timezone)}`;
    case 'calendar_cancel':
      return `${past ? 'Cancelled' : 'Cancel'} "${change.event.title}"`;
  }
}
