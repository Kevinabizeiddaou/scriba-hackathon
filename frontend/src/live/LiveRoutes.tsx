/**
 * The live workspace's routes. Every screen here reads Scriba or the Desk overlay.
 *
 * The evaluation screen is loaded on demand: it brings the suites, the scorer, the scripted
 * reference agent and the mock with it, none of which the rest of the live application uses.
 */
import { lazy, Suspense, useEffect } from 'react'
import { AppShell } from '../components/AppShell'
import { SkeletonRows } from '../components/ui'
import { FIND_A_TIME, PAGE_TITLES } from '../lib/pageTitles'
import { useRoute } from '../lib/router'
import { CalendarPage } from '../pages/CalendarPage'
import { InboxPage } from '../pages/InboxPage'
import { TasksPage } from '../pages/TasksPage'
import { LiveChatPage } from './LiveChatPage'
import { LiveOverviewPage } from './LiveOverviewPage'
import { LiveSchedulingPage } from './LiveSchedulingPage'
import { LiveActivityPage, LiveApprovalsPage } from './LiveWorkPages'
import { LiveWorkQueuePage } from './LiveWorkQueuePage'

const EvaluationPage = lazy(() => import('./LiveEvaluation'))

export function LiveRoutes() {
  const route = useRoute()

  useEffect(() => {
    document.title = `${route.page === 'calendar' && route.param === FIND_A_TIME ? 'Find a time' : PAGE_TITLES[route.page]} · Scriba Executive Desk`
  }, [route.page, route.param])

  return (
    <AppShell page={route.page}>
      {route.page === 'overview' && <LiveOverviewPage />}
      {route.page === 'inbox' && <InboxPage emailId={route.param} />}
      {route.page === 'calendar' && (route.param === FIND_A_TIME ? <LiveSchedulingPage /> : <CalendarPage eventId={route.param} />)}
      {route.page === 'tasks' && <TasksPage tab={route.param} />}
      {route.page === 'work' && <LiveWorkQueuePage runId={route.param} />}
      {route.page === 'chat' && <LiveChatPage conversationId={route.param} />}
      {route.page === 'approvals' && <LiveApprovalsPage />}
      {route.page === 'activity' && <LiveActivityPage />}
      {route.page === 'evaluation' && (
        <Suspense fallback={<div className="px-4 py-6 sm:px-6 lg:px-8" role="status" aria-label="Loading the evaluation screen"><SkeletonRows rows={5} /></div>}>
          <EvaluationPage />
        </Suspense>
      )}
    </AppShell>
  )
}
