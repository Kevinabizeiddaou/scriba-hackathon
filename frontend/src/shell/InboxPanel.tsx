import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getErrorMessage } from '../api/client'
import { fetchEmails } from '../api/scriba'
import type { MailProvider } from '../api/contract'
import type { Capability, CapabilityId } from '../lib/connections'

const MAIL: ReadonlyArray<{ provider: MailProvider; capability: CapabilityId; label: string }> = [
  { provider: 'gmail', capability: 'gmail', label: 'Gmail' },
  { provider: 'outlook', capability: 'outlook_mail', label: 'Outlook' },
]

/** Read-only in Stage 1: lists mail through Scriba's GET /emails per provider. */
export function InboxPanel({ capabilities }: { capabilities: Capability[] }) {
  const usable = MAIL.filter(
    item => capabilities.find(c => c.id === item.capability)?.state === 'connected',
  )
  const [selected, setSelected] = useState<MailProvider | null>(null)
  const provider = selected && usable.some(item => item.provider === selected)
    ? selected
    : usable[0]?.provider ?? null

  const emails = useQuery({
    queryKey: ['desk-emails', provider],
    queryFn: () => fetchEmails(provider!, { limit: 25 }),
    enabled: provider !== null,
  })

  if (!provider) {
    return (
      <section aria-labelledby="inbox-heading">
        <h2 id="inbox-heading" className="text-xl font-semibold">Inbox</h2>
        <p className="text-sm mt-2">Connect Gmail or Outlook Mail to see messages here.</p>
      </section>
    )
  }

  return (
    <section aria-labelledby="inbox-heading" className="space-y-3">
      <div className="flex items-center gap-2">
        <h2 id="inbox-heading" className="text-xl font-semibold">Inbox</h2>
        {usable.map(item => (
          <button
            key={item.provider}
            type="button"
            className={provider === item.provider ? 'btn-primary' : 'btn-secondary'}
            aria-pressed={provider === item.provider}
            onClick={() => setSelected(item.provider)}
          >
            {item.label}
          </button>
        ))}
      </div>

      {emails.isPending ? <p role="status" className="text-sm">Loading messages…</p> : null}
      {emails.isError ? (
        <p role="alert" className="text-sm">Could not load mail: {getErrorMessage(emails.error)}</p>
      ) : null}
      {emails.data && emails.data.items.length === 0 ? (
        <p className="text-sm">No messages in this mailbox.</p>
      ) : null}

      <ul className="space-y-2">
        {emails.data?.items.map(item => (
          <li key={`${item.provider}:${item.id}`} className="card p-3">
            <div className="flex items-baseline gap-2">
              <strong className={item.is_read ? 'font-medium' : 'font-semibold'}>{item.subject || '(no subject)'}</strong>
              <time className="ml-auto text-xs opacity-70" dateTime={item.timestamp}>
                {new Date(item.timestamp).toLocaleString()}
              </time>
            </div>
            <p className="text-sm opacity-80">{item.from_addr}</p>
            <p className="text-sm">{item.snippet}</p>
            {item.account_email ? (
              <p className="text-xs opacity-60">Received by {item.account_email}</p>
            ) : null}
          </li>
        ))}
      </ul>
    </section>
  )
}
