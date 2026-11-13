import { useCallback, useEffect, useRef, useState } from 'react';
import { getApi, getWorkspace, type ExecutiveDeskApi } from '../harness';
import type { WorkspaceApi } from '../harness/workspace';

export interface Resource<T> {
  data: T | undefined;
  error: Error | null;
  /** True only until the first answer arrives; refreshes keep showing the previous data. */
  loading: boolean;
  reload: () => void;
}

/**
 * Loads data through the API client and reloads it whenever the client reports a change.
 *
 * At most one request is in flight per hook. A change that arrives while one is running is
 * remembered and triggers a single follow-up request when it finishes. This matters against a
 * real backend: the HTTP adapter signals a change every two seconds, and if each signal started
 * a new request and discarded the old one, a backend slower than two seconds would never be shown.
 *
 * When `deps` change, the old data is dropped at once, so one conversation's messages are never
 * shown under another conversation's title.
 */
export function useResource<T>(load: (api: ExecutiveDeskApi) => Promise<T>, deps: readonly unknown[]): Resource<T> {
  return useLoader(() => load(getApi()), (listener) => getApi().subscribe(listener), deps);
}

/** The same, for the workspace view models (mail, calendar, tasks, follow-ups, activity). */
export function useWorkspace<T>(load: (workspace: WorkspaceApi) => Promise<T>, deps: readonly unknown[]): Resource<T> {
  return useLoader(
    () => load(getWorkspace()),
    (listener) => {
      // Workspace data also depends on the desk (approvals, runs), so listen to both.
      const off = [getWorkspace().subscribe(listener), getApi().subscribe(listener)];
      return () => off.forEach((stop) => stop());
    },
    deps,
  );
}

function useLoader<T>(load: () => Promise<T>, subscribe: (listener: () => void) => () => void, deps: readonly unknown[]): Resource<T> {
  const [state, setState] = useState<{ data: T | undefined; error: Error | null; loading: boolean }>({
    data: undefined,
    error: null,
    loading: true,
  });
  const loadRef = useRef(load);
  loadRef.current = load;
  /** Bumped when deps change or the hook unmounts; a response from an older generation is dropped. */
  const generation = useRef(0);
  const inFlight = useRef(false);
  const stale = useRef(false);

  const reload = useCallback(() => {
    if (inFlight.current) {
      stale.current = true;
      return;
    }
    inFlight.current = true;
    const startedIn = generation.current;
    loadRef
      .current()
      .then((data) => {
        if (startedIn === generation.current) setState({ data, error: null, loading: false });
      })
      .catch((error: unknown) => {
        if (startedIn === generation.current) {
          setState((previous) => ({ data: previous.data, error: error instanceof Error ? error : new Error(String(error)), loading: false }));
        }
      })
      .finally(() => {
        inFlight.current = false;
        // Either something changed while we were loading, or the answer belonged to old deps.
        if (stale.current || startedIn !== generation.current) {
          stale.current = false;
          if (generation.current >= 0) reload();
        }
      });
  }, []);

  useEffect(() => {
    const mine = Math.abs(generation.current) + 1;
    generation.current = mine;
    setState({ data: undefined, error: null, loading: true });
    reload();
    const unsubscribe = subscribe(reload);
    return () => {
      unsubscribe();
      // Negative marks "unmounted or between deps": in-flight answers are dropped and nothing restarts.
      if (generation.current === mine) generation.current = -mine;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { ...state, reload };
}
