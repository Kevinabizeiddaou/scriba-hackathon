import { useEffect } from 'react';
import { AppShell } from './components/AppShell';
import { useRoute } from './lib/router';
import { ApprovalsPage } from './pages/ApprovalsPage';
import { ChatPage } from './pages/ChatPage';
import { EvaluationPage } from './pages/EvaluationPage';
import { InboxPage } from './pages/InboxPage';

const TITLES = { chat: 'Secretary Chat', inbox: 'Request Inbox', approvals: 'Approval Center', evaluation: 'Evaluation' } as const;

export function App() {
  const route = useRoute();

  useEffect(() => {
    document.title = `${TITLES[route.page]} · Scriba Executive Desk`;
  }, [route.page]);

  return (
    <AppShell page={route.page}>
      {route.page === 'chat' && <ChatPage conversationId={route.param} />}
      {route.page === 'inbox' && <InboxPage requestId={route.param} />}
      {route.page === 'approvals' && <ApprovalsPage approvalId={route.param} />}
      {route.page === 'evaluation' && <EvaluationPage />}
    </AppShell>
  );
}
