import { useQuery } from '@tanstack/react-query'
import { getApiBaseUrl, getErrorMessage } from '../api/client'
import { fetchHealth } from '../api/scriba'

/** Which Scriba API this Desk is talking to, and whether it is healthy. */
export function SystemPanel() {
  const health = useQuery({ queryKey: ['desk-health'], queryFn: fetchHealth, retry: false })

  return (
    <section aria-labelledby="system-heading" className="space-y-3">
      <h2 id="system-heading" className="text-xl font-semibold">System</h2>
      <dl className="card p-4 grid grid-cols-[10rem_1fr] gap-y-2 text-sm">
        <dt className="opacity-70">Scriba API</dt>
        <dd data-testid="api-base">{getApiBaseUrl()}</dd>
        <dt className="opacity-70">Health</dt>
        <dd data-testid="api-health">
          {health.isPending
            ? 'Checking…'
            : health.isError
              ? `Unreachable: ${getErrorMessage(health.error)}`
              : health.data.ok
                ? 'Healthy'
                : `Degraded (${health.data.status})`}
        </dd>
        <dt className="opacity-70">Database</dt>
        <dd>{health.data ? (health.data.database?.ok ? 'Reachable' : 'Not reachable') : 'Unknown'}</dd>
        <dt className="opacity-70">Maintenance</dt>
        <dd>{health.data ? (health.data.maintenance?.maintenanceMode ? 'On' : 'Off') : 'Unknown'}</dd>
      </dl>
    </section>
  )
}
