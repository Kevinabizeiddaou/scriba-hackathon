/** Builders for Desk run payloads in tests. Shapes follow backend/desk_overlay/workflow.py (view, _action_view). */
import type { DeskAction, DeskRun } from '../api/desk'

export const deskAction = (over: Partial<DeskAction> = {}): DeskAction => ({
  toolCallId: 31,
  tool_name: 'create_task',
  status: 'awaiting_approval',
  requiresApproval: true,
  input: { title: 'Send the board pack' },
  message: null,
  error: null,
  availability: null,
  assistantActionId: null,
  verified: false,
  approve: { method: 'POST', path: '/chat/tool-calls/31/approve' },
  ...over,
})

export const executedAction = (over: Partial<DeskAction> = {}): DeskAction =>
  deskAction({ status: 'executed', approve: null, assistantActionId: 90, verified: true, ...over })

export const deskRun = (over: Partial<DeskRun> = {}): DeskRun => ({
  runId: 7,
  duplicate: false,
  state: 'awaiting_approval',
  email: {
    provider: 'gmail',
    email_id: 'm-7',
    thread_id: 't-7',
    provider_account_id: 'acct-1',
    from_addr: '"Dana Haddad" <dana@example.test>',
    subject: 'Board pack by Thursday',
  },
  category: 'action_item',
  outcome: 'task',
  createdAt: '2026-11-14T08:00:00+00:00',
  held: null,
  draftRequest: null,
  actions: [deskAction()],
  next: [],
  ...over,
})
