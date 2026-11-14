/**
 * Why the Desk is holding a proposed action, and what the user may do about it.
 *
 * The backend's own checks (BACKEND_CONTRACT section 7) hold a card as `needs_info` with an
 * `output.error_code`. Each code allows exactly one way forward, and only two of them are an
 * approval with an override the backend honours: confirming a recipient, and booking despite an
 * availability finding. Everything else is fixed elsewhere or waited out. The card offers the
 * way the contract names and no other.
 */
import type { DeskAnyHoldCode } from '../api/desk'
import { asRecord, readList } from './describeAction'
import type { ChatToolCall } from './scribaApi'

export type HoldResolution =
  /** Approve with `desk_confirmed_recipients`. */
  | 'confirm_recipients'
  /** Approve with `desk_availability_override`. */
  | 'book_anyway'
  /** A field is missing: completed in the conversation, not on the card. */
  | 'complete_in_chat'
  /** The thread changed: look at it before doing anything. Not approvable as it is. */
  | 'open_thread'
  /** A read or a check failed: nothing to decide yet. */
  | 'try_later'
  /** The execution gate refused it: nothing ran, and the card stays as it is. */
  | 'gate_closed'
  /** The provider did not confirm: look at the mailbox or calendar before any retry. */
  | 'check_first'

export interface HoldExplanation {
  title: string
  detail: string
  resolution: HoldResolution
}

/** Every code the typed client declares: the safeguards of section 7 and the execution gate of section 8. */
export type KnownHoldCode = DeskAnyHoldCode

const HOLDS: Record<KnownHoldCode, HoldExplanation> = {
  external_writes_disabled: {
    title: 'Sending mail and changing calendars are switched off on this backend',
    detail: 'Your approval was received, but the server refused to carry it out: nothing was sent and nothing was changed. The action stays here and can be approved again once the backend reports that external writes are ready.',
    resolution: 'gate_closed',
  },
  outcome_unknown: {
    title: 'The provider did not confirm, so it is not known whether this happened',
    detail: 'It may have gone through. Look in the mailbox or calendar before doing anything. In a sandbox a retry reads the result back first and does not repeat it.',
    resolution: 'check_first',
  },
  sandbox_world_gone: {
    title: 'This action was prepared in a sandbox that no longer exists',
    detail: 'It cannot run. Nothing was sent. Cancel it; the secretary will propose it again if the request comes up again.',
    resolution: 'try_later',
  },
  reply_target_missing: {
    title: 'The reply does not say which message it answers',
    detail: 'Without the message it answers, the Desk cannot check that the reply goes to the right thread. Ask the secretary to draft it again from the message.',
    resolution: 'complete_in_chat',
  },
  unverified_recipient: {
    title: 'A recipient has not been verified',
    detail: 'The address below was not given by you, is not the sender of the message being answered, and is not one of your own accounts. It may have come from the text of an email, which is untrusted.',
    resolution: 'confirm_recipients',
  },
  reply_target_changed: {
    title: 'The thread has moved on',
    detail: 'A newer message arrived in this thread, or you have already written there, so this reply would answer the wrong message. Open the thread before deciding. It cannot be approved as it is.',
    resolution: 'open_thread',
  },
  reply_target_unverified: {
    title: 'The message being answered could not be read',
    detail: 'The Desk could not confirm that this reply still answers the latest message in its thread. Nothing is wrong with the reply itself; try again later.',
    resolution: 'try_later',
  },
  recipient_required: { title: 'No recipient', detail: 'The action does not say who it goes to. Give the recipient in the conversation.', resolution: 'complete_in_chat' },
  body_required: { title: 'No message text', detail: 'The action has no text to send. Give it in the conversation.', resolution: 'complete_in_chat' },
  title_required: { title: 'No title', detail: 'The action has no title. Give one in the conversation.', resolution: 'complete_in_chat' },
  reminder_incomplete: { title: 'The reminder is incomplete', detail: 'It needs both what to remind you of and when. Give the missing part in the conversation.', resolution: 'complete_in_chat' },
  start_required: { title: 'No start time', detail: 'The event has no start time. Give one in the conversation.', resolution: 'complete_in_chat' },
  calendar_conflict: {
    title: 'The time collides with an existing commitment',
    detail: 'The calendars were read again and this time is taken. Choose another time in the conversation, or book it anyway.',
    resolution: 'book_anyway',
  },
  availability_unknown: {
    title: 'A calendar could not be read, so this time is not verified',
    detail: 'Unknown is not free. Reconnect the calendar and try again, or book it anyway knowing it may collide.',
    resolution: 'book_anyway',
  },
  desk_check_failed: {
    title: 'A safety check could not run',
    detail: 'The Desk holds an action whenever one of its own checks fails, rather than letting it through unchecked. Try again later.',
    resolution: 'try_later',
  },
}

/** The explanation for a hold code, or null for a code this version of the Desk does not know. */
export function explainHold(code: string | null | undefined): HoldExplanation | null {
  return (code && HOLDS[code as KnownHoldCode]) || null
}

export const HOLD_CODES = Object.keys(HOLDS) as KnownHoldCode[]

/** The addresses the backend could not verify on this card (`output.unverified_recipients`). */
export function unverifiedRecipients(toolCall: Pick<ChatToolCall, 'output'>): string[] {
  return readList(asRecord(toolCall.output).unverified_recipients)
}

/** The key the backend honours on an approve request, and only there, to accept recipients. */
export const CONFIRMED_RECIPIENTS_FLAG = 'desk_confirmed_recipients'
