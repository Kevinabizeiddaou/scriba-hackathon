/**
 * What a run read, fetched and made: the files that came with the message, a website errand,
 * the files the secretary made or retrieved, and changes to a workbook that wait for the user.
 *
 * Everything is the server's record (BACKEND_CONTRACT sections 13 and 14). File content is never
 * shown: the API does not send it. "Verified" appears only where the server's flag is true, and
 * a change is applied only when the user presses Apply.
 */
import clsx from 'clsx'
import { CircleAlert, Download, FileSpreadsheet, FileText, Globe, Paperclip, ShieldAlert } from 'lucide-react'
import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { getErrorMessage, getJson } from '../api/client'
import { applyDeskFileChange, dismissDeskFileChange, type DeskAttachment, type DeskFile, type DeskFileChange, type DeskRun, type DeskWorkbookOperation } from '../api/desk'
import { Button, ErrorNote, Pill } from '../components/ui'
import { SandboxTag } from './RunParts'

/** A website errand as the backend of overlay 0.6 reports it. Read loosely: an older backend sends none. */
export interface BrowserErrand {
  state: string
  site: string
  origin?: string
  goal?: string
  stepsDone: number
  stepsTotal: number
  verified: boolean
  simulated: boolean
  message?: string | null
  steps?: Array<{ index: number; op: string; name: string | null; state: string; ms?: number; message?: string; recovered?: string[]; value?: string; verification?: { verified: boolean; method?: string; checksum?: string; reason?: string } }>
  downloads?: Array<{ fileId: string; filename: string; sizeBytes: number; from: string; verified: boolean; checksum: string | null }>
  untrustedFindings?: Array<{ url: string; where: string; finding: string }>
  ignored?: Array<{ name: string; reason: string; origin: string | null }>
  blockedOrigins?: string[]
}
export const errandOf = (run: DeskRun): BrowserErrand | null => (run as DeskRun & { browser?: BrowserErrand }).browser ?? null

const size = (bytes: number | null | undefined) => (bytes == null ? '' : bytes < 1024 ? `${bytes} B` : bytes < 1024 * 1024 ? `${Math.round(bytes / 1024)} kB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`)

const READ_ERROR: Record<string, string> = {
  file_blocked: 'This kind of file is not opened.',
  file_type_mismatch: 'Its content is not what its name says.',
  file_too_large: 'It is too large to read.',
  file_unreadable: 'It could not be opened.',
  too_many_attachments: 'The message brought more files than are read.',
}

/** Fetch a file of the user's own records with their session, and hand it to the browser to save. */
async function saveFile(path: string, filename: string) {
  const blob = await getJson<Blob>(path, { responseType: 'blob' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1_000)
}

function DownloadButton({ path, filename }: { path: string; filename: string }) {
  const save = useMutation({ mutationFn: () => saveFile(path, filename) })
  return (
    <span className="inline-flex flex-col items-end gap-1">
      <Button variant="ghost" icon={Download} busy={save.isPending} onClick={() => save.mutate()} aria-label={`Download ${filename}`}>
        Download
      </Button>
      {save.isError && <span role="alert" className="text-xs text-danger">{getErrorMessage(save.error, 'The file could not be downloaded.')}</span>}
    </span>
  )
}

function AttachmentRow({ file }: { file: DeskAttachment }) {
  return (
    <li className="flex flex-wrap items-start gap-x-3 gap-y-1 py-2.5">
      <Paperclip aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-mute" />
      <div className="min-w-0 flex-1">
        <p className="break-words text-[13px] font-medium text-ink">{file.filename}</p>
        <p className="text-xs text-mute">
          {[file.kind?.toUpperCase(), size(file.sizeBytes), file.unitCount != null && file.unit ? `${file.unitCount} ${file.unit}${file.unitCount === 1 ? '' : 's'}` : null].filter(Boolean).join(' · ')}
        </p>
        {!file.read && <p className="mt-1 text-xs text-warn">Not read. {READ_ERROR[file.error ?? ''] ?? (file.error ? `Reason reported: ${file.error.replace(/_/g, ' ')}.` : '')}</p>}
        {file.read && file.unreadParts > 0 && <p className="mt-1 text-xs text-warn">{file.unreadParts} scanned page{file.unreadParts === 1 ? ' was' : 's were'} not read.</p>}
        {file.untrustedFindings > 0 && <p role="alert" className="mt-1 text-xs text-warn">This file carries text written to an assistant. Nothing was proposed from it.</p>}
      </div>
      <Pill tone={file.read ? 'neutral' : 'warn'} icon={null}>{file.read ? 'Read' : 'Not read'}</Pill>
    </li>
  )
}

function FileRow({ file }: { file: DeskFile }) {
  const source = (file as DeskFile & { source?: string }).source
  const Icon = /sheet|excel/.test(file.mimeType) || /\.xlsx$/i.test(file.filename) ? FileSpreadsheet : FileText
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2.5">
      <Icon aria-hidden className="h-4 w-4 shrink-0 text-accent" />
      <div className="min-w-0 flex-1">
        <p className="break-words text-[13px] font-medium text-ink">{file.filename}</p>
        <p className="text-xs text-mute">
          {[source === 'browser' ? 'Retrieved from a website' : file.changeId ? 'Changed copy of a workbook' : 'Made by the secretary', size(file.sizeBytes)].filter(Boolean).join(' · ')}
        </p>
        {!file.verified && <p className="mt-1 text-xs text-warn">{file.state === 'VERIFICATION_FAILED' ? 'The file was written but does not show what was approved.' : 'Not verified.'}</p>}
      </div>
      <Pill tone={file.verified ? 'ok' : 'warn'}>{file.verified ? 'Verified' : 'Not verified'}</Pill>
      <DownloadButton path={file.download.path} filename={file.filename} />
    </li>
  )
}

const cellValue = (value: unknown) => (value === null || value === undefined || value === '' ? 'empty' : String(value))

export function describeOperation(op: DeskWorkbookOperation): string {
  if (op.op === 'update_cell') return `${op.sheet}, cell ${op.cell}: set to ${cellValue(op.value)}`
  const pairs = Object.entries(op.values).map(([header, value]) => `${header} = ${cellValue(value)}`).join(', ')
  return op.op === 'append_row' ? `${op.sheet}: add a row (${pairs})` : `${op.sheet}: where ${op.key} is ${cellValue(op.values[op.key])}, set ${pairs}`
}

const CHANGE_STATE: Record<DeskFileChange['state'], { label: string; tone: 'ok' | 'warn' | 'danger' | 'neutral' }> = {
  suggested: { label: 'Waiting for you', tone: 'warn' },
  applied: { label: 'Applied and verified', tone: 'ok' },
  unverified: { label: 'Not confirmed', tone: 'warn' },
  failed: { label: 'Not applied', tone: 'danger' },
  dismissed: { label: 'Set aside', tone: 'neutral' },
}

function FileChange({ runId, change, onChanged }: { runId: number; change: DeskFileChange; onChanged: (run: DeskRun) => void }) {
  const [open, setOpen] = useState(change.state === 'suggested')
  const apply = useMutation({ mutationFn: () => applyDeskFileChange(runId, change.id), onSuccess: onChanged })
  const dismiss = useMutation({ mutationFn: () => dismissDeskFileChange(runId, change.id), onSuccess: onChanged })
  const state = CHANGE_STATE[change.state] ?? { label: change.state, tone: 'warn' as const }
  const busy = apply.isPending || dismiss.isPending
  return (
    <li className={clsx('rounded-xl border p-3.5', change.state === 'suggested' ? 'border-warn/35 bg-warn/[0.05]' : 'border-line')} data-testid="file-change" data-state={change.state}>
      <div className="flex flex-wrap items-center gap-2">
        <FileSpreadsheet aria-hidden className="h-4 w-4 shrink-0 text-accent" />
        <p className="min-w-0 flex-1 break-words text-[13.5px] font-semibold text-ink">{change.filename}</p>
        <Pill tone={state.tone}>{state.label}</Pill>
        {change.simulated && <SandboxTag />}
      </div>
      <p className="mt-1.5 text-[12.5px] leading-[19px] text-soft">
        {change.state === 'suggested' && 'A changed copy will be made and checked. The original file stays as it is.'}
        {change.state === 'applied' && `Changed copy: ${change.resultFilename}. It was opened again and compared with the original, which was left as it was.`}
        {change.state === 'failed' && (change.message ?? 'The change could not be made. Nothing was kept and the original is unchanged.')}
        {change.state === 'unverified' && 'The file store did not confirm. A copy may or may not exist; this is not a success.'}
        {change.state === 'dismissed' && (change.dismissedFrom && change.dismissedFrom !== 'suggested' ? `Set aside after it was ${change.dismissedFrom === 'failed' ? 'not applied' : 'not confirmed'}.` : 'Set aside. Nothing was changed.')}
      </p>
      <button type="button" onClick={() => setOpen(value => !value)} aria-expanded={open} className="mt-2 cursor-pointer text-[12.5px] font-medium text-accent hover:underline">
        {open ? 'Hide' : 'Show'} the {change.operations.length} change{change.operations.length === 1 ? '' : 's'}
      </button>
      {open && (
        <ol className="mt-2 space-y-1.5 text-[12.5px] leading-[19px] text-soft">
          {change.operations.map((op, index) => {
            const step = change.steps.find(s => s.index === index + 1)
            return (
              <li key={index} className={clsx('flex gap-2', change.failedAt === index + 1 && 'text-danger')}>
                <span className="w-5 shrink-0 tabular-nums text-mute">{index + 1}.</span>
                <span className="min-w-0 break-words">
                  {describeOperation(op)}
                  {step?.error ? ` (${step.error})` : ''}
                  {change.failedAt != null && index + 1 > change.failedAt ? ' (never ran)' : ''}
                </span>
              </li>
            )
          })}
        </ol>
      )}
      {change.state === 'suggested' && (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Button variant="primary" busy={apply.isPending} disabled={busy} onClick={() => apply.mutate()}>Apply to a copy</Button>
          <Button variant="ghost" busy={dismiss.isPending} disabled={busy} onClick={() => dismiss.mutate()}>Dismiss</Button>
        </div>
      )}
      {(change.state === 'failed' || change.state === 'unverified') && (
        <div className="mt-3">
          <Button variant="ghost" busy={dismiss.isPending} disabled={busy} onClick={() => dismiss.mutate()}>Set aside</Button>
        </div>
      )}
      {(apply.isError || dismiss.isError) && <div className="mt-2"><ErrorNote error={new Error(getErrorMessage(apply.error ?? dismiss.error))} /></div>}
    </li>
  )
}

const ERRAND_STATE: Record<string, { label: string; tone: 'ok' | 'warn' | 'danger' | 'info' | 'neutral' }> = {
  PLANNED: { label: 'Planned', tone: 'info' },
  RUNNING: { label: 'Browsing', tone: 'info' },
  VERIFIED: { label: 'Done and verified', tone: 'ok' },
  COMPLETED: { label: 'Read; nothing to verify', tone: 'neutral' },
  FAILED: { label: 'Failed', tone: 'danger' },
  HELD: { label: 'Held', tone: 'warn' },
  NEEDS_APPROVAL: { label: 'Needs your approval', tone: 'warn' },
  NOT_APPLIED: { label: 'Not applied', tone: 'danger' },
  OUTCOME_UNKNOWN: { label: 'Outcome unknown', tone: 'warn' },
  INTERRUPTED: { label: 'Interrupted', tone: 'warn' },
  CANCELLED: { label: 'Cancelled', tone: 'neutral' },
}
const RECOVERED: Record<string, string> = {
  signed_in: 'signed in',
  slow_page_tried_again: 'tried a slow page again',
  kept_locator_no_longer_fits: 'looked the control up again',
  answer_missing_or_unexpected_read_back_instead: 'no answer came, so the site was read back; it was submitted once',
}
const recovered = (code: string) => (code.startsWith('closed_dialog') ? 'closed a dialog' : code.startsWith('download_tried_again') ? 'tried the download again' : (RECOVERED[code] ?? code.replace(/_/g, ' ')))
const OP: Record<string, string> = { open: 'Open', follow: 'Follow', read: 'Read', find_row: 'Find', download: 'Download', fill: 'Fill in', submit: 'Submit', expect: 'Check' }

function Errand({ errand }: { errand: BrowserErrand }) {
  const state = ERRAND_STATE[errand.state] ?? { label: errand.state, tone: 'warn' as const }
  return (
    <section aria-label="Website" className="card space-y-3 p-4 sm:p-5" data-testid="browser-errand" data-state={errand.state}>
      <div className="flex flex-wrap items-center gap-2">
        <Globe aria-hidden className="h-4 w-4 text-accent" />
        <h2 className="text-[14.5px] font-semibold text-ink">Website: {errand.site}</h2>
        <Pill tone={state.tone} spin={errand.state === 'RUNNING'}>{state.label}</Pill>
        {errand.simulated && <SandboxTag />}
      </div>
      <p className="text-[12.5px] leading-[19px] text-soft">
        {errand.goal ? `${errand.goal}. ` : ''}
        {errand.stepsDone} of {errand.stepsTotal} steps done{errand.origin ? ` on ${errand.origin}` : ''}. Opening, reading and downloading run without asking; nothing was submitted to the site.
      </p>
      {errand.message && errand.state !== 'VERIFIED' && errand.state !== 'COMPLETED' && <p role="alert" className="rounded-lg border border-danger/30 bg-danger/[0.07] px-3 py-2 text-[12.5px] leading-[19px] text-danger">{errand.message}</p>}
      {(errand.untrustedFindings?.length ?? 0) > 0 && (
        <p role="alert" className="flex items-start gap-2 rounded-lg border border-warn/30 bg-warn/[0.07] px-3 py-2 text-[12.5px] leading-[19px] text-warn">
          <ShieldAlert aria-hidden className="mt-0.5 h-4 w-4 shrink-0" />
          <span>The site carries text written to an assistant ({[...new Set(errand.untrustedFindings!.map(f => (f.where === 'hidden' ? 'hidden in the page' : 'shown on the page')))].join(' and ')}). It was not followed.</span>
        </p>
      )}
      {(errand.ignored?.length ?? 0) > 0 && <p className="text-[12.5px] text-soft">A link to another site was not used: {errand.ignored!.map(i => `"${i.name}"${i.origin ? ` (${i.origin})` : ''}`).join(', ')}.</p>}
      {(errand.blockedOrigins?.length ?? 0) > 0 && <p className="text-[12.5px] text-soft">The page tried to reach another site and was refused: {errand.blockedOrigins!.join(', ')}.</p>}
      {(errand.steps?.length ?? 0) > 0 && (
        <ol aria-label="Steps the browser took" className="divide-y divide-line">
          {errand.steps!.map(step => (
            <li key={step.index} className="flex flex-wrap items-start gap-x-3 gap-y-0.5 py-2 text-[12.5px] leading-[19px]">
              <span className="w-5 shrink-0 tabular-nums text-mute">{step.index}.</span>
              <span className="min-w-0 flex-1 break-words text-soft">
                <span className="font-medium text-ink">{OP[step.op] ?? step.op}</span> {step.name}
                {step.value ? `: ${step.value}` : ''}
                {(step.recovered?.length ?? 0) > 0 && <span className="block text-xs text-mute">On the way: {step.recovered!.map(recovered).join('; ')}.</span>}
                {step.verification && <span className={clsx('block text-xs', step.verification.verified ? 'text-ok' : 'text-danger')}>{step.verification.verified ? (step.verification.method === 'file_opened' ? `The file was opened${step.verification.checksum === 'matches_the_page' ? ' and has the checksum the page states' : ''}.` : 'The site was read again and shows the change.') : `Not verified${step.verification.reason ? `: ${step.verification.reason.replace(/_/g, ' ')}` : ''}.`}</span>}
                {step.state !== 'done' && step.message && <span className="block text-xs text-danger">{step.message}</span>}
              </span>
              <span className="shrink-0 text-xs tabular-nums text-mute">{step.state === 'done' ? (step.ms != null ? `${Math.round(step.ms)} ms` : 'done') : step.state === 'submitting' ? 'submitted, answer not on record' : 'stopped'}</span>
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}

export function RunDeliverables({ run, onChanged }: { run: DeskRun; onChanged: (run: DeskRun) => void }) {
  const attachments = run.attachments ?? []
  const files = run.files ?? []
  const changes = run.fileChanges ?? []
  const errand = errandOf(run)
  if (attachments.length + files.length + changes.length === 0 && !errand) return null
  return (
    <>
      {errand && <Errand errand={errand} />}
      {changes.length > 0 && (
        <section aria-label="Workbook changes" className="card space-y-3 p-4 sm:p-5">
          <div className="flex items-center gap-2">
            <h2 className="text-[14.5px] font-semibold text-ink">Workbook changes</h2>
            {changes.some(c => c.state === 'suggested') && <CircleAlert aria-hidden className="h-4 w-4 text-warn" />}
          </div>
          <ul className="space-y-2.5">
            {changes.map(change => <FileChange key={change.id} runId={run.runId} change={change} onChanged={onChanged} />)}
          </ul>
        </section>
      )}
      {(attachments.length > 0 || files.length > 0) && (
        <section aria-label="Files" className="card p-4 sm:p-5">
          <h2 className="text-[14.5px] font-semibold text-ink">Files</h2>
          {files.length > 0 && (
            <>
              <p className="eyebrow mt-3">Made or retrieved by the secretary</p>
              <ul className="divide-y divide-line">{files.map(file => <FileRow key={file.id} file={file} />)}</ul>
            </>
          )}
          {attachments.length > 0 && (
            <>
              <p className="eyebrow mt-3">Came with the message</p>
              <ul className="divide-y divide-line">{attachments.map(file => <AttachmentRow key={file.id} file={file} />)}</ul>
            </>
          )}
        </section>
      )}
    </>
  )
}
