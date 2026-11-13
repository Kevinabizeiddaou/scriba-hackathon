import { useEffect } from 'react';
import { AppShell } from './components/AppShell';
import { getWorkspace } from './harness';
import { useRoute, type Page } from './lib/router';
import { LiveChatPage } from './live/LiveChatPage';
import { LiveOverviewPage } from './live/LiveOverviewPage';
import { LiveActivityPage, LiveApprovalsPage } from './live/LiveWorkPages';
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

/**
 * The workspace: one shell, one set of routes.
 *
 * Inbox, calendar and tasks are the same screens on live and on mock data; they read view models
 * and the data layer decides where those come from. The overview, chat, approvals and activity
 * have a live version, because on Scriba those run on its chat agent and its action records,
 * which the mock's scripted runs do not resemble.
 */
export function Desk() {
  const route = useRoute();
  const live = getWorkspace().availability === 'live';

  useEffect(() => {
    document.title = `${TITLES[route.page]} · Scriba Executive Desk`;
  }, [route.page]);

  return (
    <AppShell page={route.page}>
      {route.page === 'overview' && (live ? <LiveOverviewPage /> : <OverviewPage />)}
      {route.page === 'inbox' && <InboxPage emailId={route.param} />}
      {route.page === 'calendar' && <CalendarPage eventId={route.param} />}
      {route.page === 'tasks' && <TasksPage tab={route.param} />}
      {route.page === 'chat' && (live ? <LiveChatPage conversationId={route.param} /> : <ChatPage conversationId={route.param} />)}
      {route.page === 'approvals' && (live ? <LiveApprovalsPage /> : <ApprovalsPage approvalId={route.param} />)}
      {route.page === 'activity' && (live ? <LiveActivityPage /> : <ActivityPage />)}
      {route.page === 'evaluation' && <EvaluationPage />}
    </AppShell>
  );
}
