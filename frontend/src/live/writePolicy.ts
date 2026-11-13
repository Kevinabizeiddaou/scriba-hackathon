/**
 * Which approvals the Desk will let the user give.
 *
 * Approving a card on Scriba executes it for real. Sending mail and changing a calendar reach
 * people outside the Desk and cannot be taken back, so the Desk allows those approvals only when
 * the backend it is talking to says its safety fixes are in place. Until then the card is shown
 * in full, with its recipients, account and changes, and the Approve control is disabled with
 * the reason. Cancelling a card is always allowed.
 *
 * Creating a task or a reminder writes only to Scriba's own records for the signed-in user, so
 * those approvals are allowed.
 *
 * The signal is `externalWrites.enabled === true` on GET /desk/health. That field is PROPOSED:
 * no backend sets it today, so on every current backend external approvals are off. It is the
 * one thing the backend owner has to add to switch them on; see
 * docs/frontend/LIVE_INTEGRATION.md.
 */
import type { DeskHealth } from '../api/desk'

export type ToolEffect = 'read' | 'internal_write' | 'external_write' | 'excluded' | 'unknown'

const READ = new Set([
  'search_sources', 'show_agenda', 'show_meetings', 'provider_status', 'list_tasks', 'summarize_emails',
  'check_availability', 'find_free_slots', 'executive_briefing',
])
const INTERNAL = new Set(['create_task', 'create_reminder'])
const EXTERNAL = new Set([
  'draft_email_reply', 'send_email', 'create_calendar_event', 'update_calendar_event', 'cancel_calendar_event',
])
/** Integrations the Desk leaves out. Scriba's unscoped chat agent can still propose these. */
const EXCLUDED_PREFIXES = ['send_slack', 'send_teams', 'create_jira', 'comment_jira', 'transition_jira', 'drive_', 'onedrive_', 'upload_', 'desktop_']
const EXCLUDED = new Set(['create_spreadsheet', 'create_document', 'run_automation_with_file', 'query_table', 'capture_note', 'remember_fact'])

export function toolEffect(toolName: string): ToolEffect {
  if (READ.has(toolName)) return 'read'
  if (INTERNAL.has(toolName)) return 'internal_write'
  if (EXTERNAL.has(toolName)) return 'external_write'
  if (EXCLUDED.has(toolName) || EXCLUDED_PREFIXES.some(prefix => toolName.startsWith(prefix))) return 'excluded'
  return 'unknown'
}

export type DeskHealthWithPolicy = DeskHealth & {
  /** Proposed. Set by the backend only when its send and calendar safety fixes are verified. */
  externalWrites?: { enabled?: boolean; revision?: string | null }
  /** Present on a backend with the Desk chat scope: "enforced" or "off". */
  chatScope?: string
}

export interface WritePolicy {
  externalWritesEnabled: boolean
  /** True when the backend narrows the chat agent to Desk tools and gates bookings on availability. */
  chatScopeEnforced: boolean
}

export function writePolicyFrom(health: DeskHealthWithPolicy | null | undefined): WritePolicy {
  return {
    externalWritesEnabled: health?.externalWrites?.enabled === true,
    chatScopeEnforced: health?.chatScope === 'enforced',
  }
}

export interface ApprovalGate {
  allowed: boolean
  /** Shown next to the disabled control. Null when allowed. */
  reason: string | null
}

export function approvalGate(toolName: string, policy: WritePolicy): ApprovalGate {
  const effect = toolEffect(toolName)
  if (effect === 'internal_write' || effect === 'read') return { allowed: true, reason: null }
  if (effect === 'excluded') {
    return { allowed: false, reason: 'This action uses an integration that is not part of the Executive Desk. It can be cancelled here, not approved.' }
  }
  if (effect === 'unknown') {
    return { allowed: false, reason: 'The Desk does not recognise this action, so it will not approve it. It can be cancelled here.' }
  }
  if (!policy.externalWritesEnabled) {
    return {
      allowed: false,
      reason: 'Sending mail and changing calendars are switched off: this backend has not reported that its safety fixes are in place. You can review and cancel this action; approving it stays disabled until then.',
    }
  }
  return { allowed: true, reason: null }
}
