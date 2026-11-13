import { useEffect } from 'react';
import { AppShell } from './components/AppShell';
import { useRoute, type Page } from './lib/router';
import { ActivityPage } from './pages/ActivityPage';
import { ApprovalsPage } from './pages/ApprovalsPage';
import { CalendarPage } from './pages/CalendarPage';
import { ChatPage } from './pages/ChatPage';
import { EvaluationPage } from './pages/EvaluationPage';
import { InboxPage } from './pages/InboxPage';
import { OverviewPage } from './pages/OverviewPage';
import { TasksPage } from './pages/TasksPage';

const TITLES: Record<Page, string> = {
  overview: 'Overview',
  inbox: 'Inbox',
  calendar: 'Calendar',
  tasks: 'Tasks and follow-ups',
  chat: 'Secretary chat',
  approvals: 'Approval center',
  activity: 'Activity',
  evaluation: 'Evaluation',
};

export function App() {
  const route = useRoute();

  useEffect(() => {
    document.title = `${TITLES[route.page]} · Scriba Executive Desk`;
  }, [route.page]);

  return (
    <AppShell page={route.page}>
      {route.page === 'overview' && <OverviewPage />}
      {route.page === 'inbox' && <InboxPage emailId={route.param} />}
      {route.page === 'calendar' && <CalendarPage eventId={route.param} />}
      {route.page === 'tasks' && <TasksPage tab={route.param} />}
      {route.page === 'chat' && <ChatPage conversationId={route.param} />}
      {route.page === 'approvals' && <ApprovalsPage approvalId={route.param} />}
      {route.page === 'activity' && <ActivityPage />}
      {route.page === 'evaluation' && <EvaluationPage />}
    </AppShell>
  );
}
