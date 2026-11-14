/**
 * Replies the secretary is waiting for, from GET /desk/follow-ups (overlay 0.3).
 *
 * A follow-up opens when a reply the Desk sent has executed and expects an answer. The server
 * moves it: waiting, then answered when that person writes in the thread, or overdue after two
 * days, when one reminder is PROPOSED for approval. Nothing here sends anything. "Stop waiting"
 * closes the follow-up through the backend; it does not send a message either.
 */
import { MailQuestion, RefreshCw } from 'lucide-react'
import { useEffect } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { getErrorMessage } from '../api/client'
import { closeDeskFollowUp, fetchDeskFollowUps, type DeskFollowUp } from '../api/desk'
import { Button, EmptyState, ErrorNote, SkeletonRows } from '../components/ui'
import { getApi } from '../harness'
import { RUNS_KEY } from './deskRuns'
import { FollowUpItem } from './RunParts'
import { FOLLOW_UP_ORDER, FOLLOW_UP_STATE, FOLLOW_UP_STATE_REVISED, followUpInfo } from './runLifecycle'
import type { LiveSession } from './session'

export const FOLLOW_UPS_KEY = ['desk', 'follow-ups'] as const

/** True when this backend says it tracks awaited replies. */
export const tracksFollowUps = (session: LiveSession | null): boolean => session?.overlay === 'ok' && (session.health?.capabilities ?? []).includes('follow_ups')

export const openFollowUps = (followUps: DeskFollowUp[]): number => followUps.filter(followUp => followUp.state === 'waiting' || followUp.state === 'overdue').length

export function LiveFollowUps({ onCount }: { onCount?: (open: number) => void }) {
  const queryClient = useQueryClient()
  const tz = getApi().info.principal.timezone
  // `refresh` asks the server to look at the mailboxes again before answering. It reads mail; it sends nothing.
  const list = useQuery({ queryKey: FOLLOW_UPS_KEY, queryFn: () => fetchDeskFollowUps({ refresh: true }) })
  const close = useMutation({
    mutationFn: (followUp: DeskFollowUp) => closeDeskFollowUp(followUp.runId as number, followUp.id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: FOLLOW_UPS_KEY })
      void queryClient.invalidateQueries({ queryKey: RUNS_KEY })
    },
  })

  const followUps = list.data?.followUps ?? []
  const open = openFollowUps(followUps)
  useEffect(() => {
    if (list.data) onCount?.(open)
  }, [list.data, open, onCount])

  if (list.isPending) return <SkeletonRows rows={3} />
  if (list.isError) return <ErrorNote error={new Error(`The follow-ups could not be read: ${getErrorMessage(list.error)}. Nothing is shown rather than an old list.`)} onRetry={() => void list.refetch()} />

  if (followUps.length === 0) {
    return (
      <EmptyState icon={MailQuestion} title="No reply is being waited for">
        A follow-up opens here when a reply the secretary sent, after your approval, expects an answer: times it offered, or a question it asked. Mail you send yourself is not tracked.
      </EmptyState>
    )
  }

  // States this version knows, in the order a person works them; anything else is listed last, as unrecognised.
  const revised = Object.keys(FOLLOW_UP_STATE_REVISED)
  const known = [...(FOLLOW_UP_ORDER as string[]), ...revised]
  const groups = [...revised.map(state => ({ state, items: followUps.filter(followUp => (followUp.state as string) === state) })), ...FOLLOW_UP_ORDER.map(state => ({ state: state as string, items: followUps.filter(followUp => followUp.state === state) })), { state: 'other', items: followUps.filter(followUp => !known.includes(followUp.state)) }].filter(group => group.items.length > 0)

  return (
    <div className="space-y-5" aria-label="Follow-ups">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-[12.5px] text-soft" data-testid="follow-up-counts">
          {FOLLOW_UP_ORDER.map(state => `${followUps.filter(followUp => followUp.state === state).length} ${FOLLOW_UP_STATE[state].label.toLowerCase()}`).join(' · ')}
        </p>
        <Button icon={RefreshCw} className="h-8" onClick={() => void list.refetch()} busy={list.isFetching}>Read the mailboxes again</Button>
      </div>
      {close.isError && <p role="alert" className="text-[12.5px] text-danger">The follow-up could not be closed: {getErrorMessage(close.error)}. It is still open.</p>}
      {groups.map(group => (
        <section key={group.state} aria-label={group.state === 'other' ? 'State not recognised' : followUpInfo(group.state).label}>
          <h2 className="eyebrow mb-2">{group.state === 'other' ? 'State not recognised' : followUpInfo(group.state).label} ({group.items.length})</h2>
          {group.state === 'overdue' && <p className="mb-2 text-[12.5px] text-soft">A reminder is proposed on each run for your approval. It is a suggestion: it has not been sent.</p>}
          <ul className="space-y-2">
            {group.items.map(followUp => (
              <FollowUpItem key={`${followUp.runId}-${followUp.id}`} followUp={followUp} timeZone={tz} onClose={typeof followUp.runId === 'number' ? () => close.mutate(followUp) : undefined} closing={close.isPending && close.variables?.id === followUp.id} />
            ))}
          </ul>
        </section>
      ))}
    </div>
  )
}
