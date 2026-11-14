import { useEffect } from 'react';
import { AppShell } from './components/AppShell';
import { useRoute } from './lib/router';
import { PAGE_TITLES } from './lib/pageTitles';
import { ActivityPage } from './pages/ActivityPage';
import { ApprovalsPage } from './pages/ApprovalsPage';
import { CalendarPage } from './pages/CalendarPage';
import { ChatPage } from './pages/ChatPage';
import { EvaluationPage } from './pages/EvaluationPage';
import { InboxPage } from './pages/InboxPage';
import { OverviewPage } from './pages/OverviewPage';
import { TasksPage } from './pages/TasksPage';
import { WorkQueueDemoNotice } from './pages/WorkQueueDemoNotice';

/**
 * The workspace on mock data: demo mode, the contract-v1 mode and the screen tests.
 *
 * The live application has its own route table (src/live/LiveRoutes.tsx). Inbox, calendar and
 * tasks are the same screens in both; they read view models and the data layer decides where
 * those come from. The overview, chat, approvals and activity differ, because on Scriba those run
 * on its chat agent and its action records, which the mock's scripted runs do not resemble.
 */
export function Desk() {
  const route = useRoute();

  useEffect(() => {
    document.title = `${PAGE_TITLES[route.page]} · Scriba Executive Desk`;
  }, [route.page]);

  return (
    <AppShell page={route.page}>
      {route.page === 'overview' && <OverviewPage />}
      {route.page === 'inbox' && <InboxPage emailId={route.param} />}
      {route.page === 'calendar' && <CalendarPage eventId={route.param} />}
      {route.page === 'tasks' && <TasksPage tab={route.param} />}
      {route.page === 'work' && <WorkQueueDemoNotice />}
      {route.page === 'chat' && <ChatPage conversationId={route.param} />}
      {route.page === 'approvals' && <ApprovalsPage approvalId={route.param} />}
      {route.page === 'activity' && <ActivityPage />}
      {route.page === 'evaluation' && <EvaluationPage />}
    </AppShell>
  );
}
