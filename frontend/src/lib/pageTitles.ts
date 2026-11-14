import type { Page } from './router';

export const PAGE_TITLES: Record<Page, string> = {
  overview: 'Home',
  inbox: 'Inbox',
  calendar: 'Calendar',
  tasks: 'Tasks and follow-ups',
  work: 'Automations',
  chat: 'Chat',
  approvals: 'Approvals',
  activity: 'Activity',
  evaluation: 'Evaluation',
};

/** `#/calendar/find-a-time`: the scheduling workspace. Any other calendar parameter is an event id. */
export const FIND_A_TIME = 'find-a-time';
