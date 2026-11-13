import { backendUrl } from '../api/client'
import type { ProviderStatusPayload } from '../api/contract'
import { STATE_LABEL, type Capability } from '../lib/connections'

interface Props {
  capabilities: Capability[]
  status: ProviderStatusPayload
}

const VENDOR_LABEL = { google: 'Google', microsoft: 'Microsoft' } as const

/**
 * Connection truth comes from Scriba's GET /providers/status. Connecting or
 * repairing an account navigates to Scriba's own OAuth start route; the grant,
 * the token and its encryption stay in Scriba.
 */
export function ConnectionsPanel({ capabilities, status }: Props) {
  const mailboxes = status.emailAccounts ?? []

  return (
    <section aria-labelledby="connections-heading" className="space-y-4">
      <h2 id="connections-heading" className="text-xl font-semibold">Connections</h2>

      <ul className="grid gap-3 sm:grid-cols-2">
        {capabilities.map(item => (
          <li key={item.id} className="card p-4 space-y-2" data-testid={`capability-${item.id}`}>
            <div className="flex items-center gap-2">
              <strong>{item.label}</strong>
              <span className="chip" data-state={item.state}>{STATE_LABEL[item.state]}</span>
            </div>
            <p className="text-sm opacity-80">
              {item.email || (item.state === 'unavailable' && item.reason
                ? `Server reports: ${item.reason}`
                : `${VENDOR_LABEL[item.vendor]} account`)}
            </p>
            {item.state === 'disconnected' || item.state === 'reconnect_required' ? (
              <a className="btn-secondary inline-block" href={backendUrl(item.loginPath)}>
                {item.state === 'reconnect_required' ? 'Reconnect' : 'Connect'} {VENDOR_LABEL[item.vendor]}
              </a>
            ) : null}
          </li>
        ))}
      </ul>

      {mailboxes.length > 0 ? (
        <div className="card p-4">
          <h3 className="font-semibold mb-2">Sending mailboxes</h3>
          <ul className="text-sm space-y-1">
            {mailboxes.map(account => (
              <li key={`${account.provider}:${account.providerAccountId}`}>
                {account.label}: {account.email}
                {account.isPrimary ? ' (primary)' : ''}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  )
}
