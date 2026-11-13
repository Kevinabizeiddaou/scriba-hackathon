import { useCallback, useEffect, useRef, useState } from 'react';
import { getApi, type ExecutiveDeskApi } from '../api';

export interface Resource<T> {
  data: T | undefined;
  error: Error | null;
  /** True only until the first answer arrives; refreshes keep showing the previous data. */
  loading: boolean;
  reload: () => void;
}

/**
 * Loads data through the API client and reloads it whenever the client reports a change.
 * A response that arrives after a newer request was started is dropped.
 */
export function useResource<T>(load: (api: ExecutiveDeskApi) => Promise<T>, deps: readonly unknown[]): Resource<T> {
  const [state, setState] = useState<{ data: T | undefined; error: Error | null; loading: boolean }>({
    data: undefined,
    error: null,
    loading: true,
  });
  const latest = useRef(0);
  const loadRef = useRef(load);
  loadRef.current = load;

  const reload = useCallback(() => {
    const ticket = ++latest.current;
    loadRef
      .current(getApi())
      .then((data) => {
        if (ticket === latest.current) setState({ data, error: null, loading: false });
      })
      .catch((error: unknown) => {
        if (ticket === latest.current) {
          setState((previous) => ({ data: previous.data, error: error instanceof Error ? error : new Error(String(error)), loading: false }));
        }
      });
  }, []);

  useEffect(() => {
    setState((previous) => ({ ...previous, loading: previous.data === undefined }));
    reload();
    const unsubscribe = getApi().subscribe(reload);
    return () => {
      unsubscribe();
      latest.current += 1; // drop anything still in flight
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { ...state, reload };
}
