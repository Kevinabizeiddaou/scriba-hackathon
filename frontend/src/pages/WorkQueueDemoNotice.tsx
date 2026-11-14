import { ClipboardList } from 'lucide-react';
import { EmptyState, PageHeader } from '../components/ui';

/** Demo mode has no backend, so it has no runs. Said plainly instead of filling the screen with invented ones. */
export function WorkQueueDemoNotice() {
  return (
    <div>
      <PageHeader title="Work queue" subtitle="Every request the secretary has picked up, where it stands, and what it needs from you." />
      <div className="max-w-3xl px-4 pb-12 sm:px-6 lg:px-8">
        <EmptyState icon={ClipboardList} title="The work queue needs a live backend">
          It shows the Desk's runs from Scriba. Demo mode has no backend, so there is nothing to list here. The inbox and the approval center show the demo's scripted requests.
        </EmptyState>
      </div>
    </div>
  );
}
