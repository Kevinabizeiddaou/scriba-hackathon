/** Minimal hash router: "#/inbox/req-001" -> { page: 'inbox', param: 'req-001' }. Every screen is deep-linkable. The default is the overview. */
import { useEffect, useState } from 'react';

export const PAGES = ['overview', 'inbox', 'calendar', 'tasks', 'work', 'chat', 'approvals', 'activity', 'jira', 'evaluation'] as const;
export type Page = (typeof PAGES)[number];

export interface Route {
  page: Page;
  param: string | null;
}

export function parseHash(hash: string): Route {
  const [page, param] = hash.replace(/^#\/?/, '').split('/');
  return {
    page: (PAGES as readonly string[]).includes(page) ? (page as Page) : 'overview',
    param: param ? decodeURIComponent(param) : null,
  };
}

export function hrefFor(page: Page, param?: string | null): string {
  return param ? `#/${page}/${encodeURIComponent(param)}` : `#/${page}`;
}

export function navigate(page: Page, param?: string | null): void {
  window.location.hash = hrefFor(page, param).slice(1);
}

export function useRoute(): Route {
  const [route, setRoute] = useState<Route>(() => parseHash(window.location.hash));
  useEffect(() => {
    const onChange = () => setRoute(parseHash(window.location.hash));
    window.addEventListener('hashchange', onChange);
    return () => window.removeEventListener('hashchange', onChange);
  }, []);
  return route;
}
