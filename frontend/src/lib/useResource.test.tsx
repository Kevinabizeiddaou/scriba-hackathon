import { act, cleanup, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { setApi, type ExecutiveDeskApi } from '../harness';
import { useResource } from './useResource';

/** A stand-in for the API client: it only needs to deliver change signals. */
let signal: () => void;
let subscribers: number;

/** Each call to `load` returns a promise the test settles by hand, as a slow backend would. */
let pending: { resolve: (value: string) => void; reject: (error: Error) => void }[];
const load = () =>
  new Promise<string>((resolve, reject) => {
    pending.push({ resolve, reject });
  });

function Probe({ id }: { id: string }) {
  const resource = useResource(() => load(), [id]);
  return (
    <p>
      {id}:{resource.loading ? 'loading' : (resource.data ?? 'none')}
      {resource.error ? ` error=${resource.error.message}` : ''}
    </p>
  );
}

const settle = async (index: number, value: string) => {
  await act(async () => {
    pending[index].resolve(value);
    await Promise.resolve();
  });
};

beforeEach(() => {
  pending = [];
  subscribers = 0;
  const listeners = new Set<() => void>();
  signal = () => listeners.forEach((listener) => listener());
  setApi({
    subscribe: (listener: () => void) => {
      listeners.add(listener);
      subscribers += 1;
      return () => {
        listeners.delete(listener);
        subscribers -= 1;
      };
    },
  } as unknown as ExecutiveDeskApi);
});

afterEach(() => {
  cleanup();
  setApi(null);
});

describe('useResource', () => {
  it('keeps one request in flight while change signals arrive, then shows the slow answer', async () => {
    render(<Probe id="a" />);
    expect(pending).toHaveLength(1);

    // The HTTP adapter signals every two seconds. A backend slower than that must still be shown.
    act(() => {
      signal();
      signal();
      signal();
    });
    expect(pending).toHaveLength(1); // no pile-up, and the first request was not thrown away

    await settle(0, 'first');
    expect(screen.getByText('a:first')).toBeInTheDocument();

    // The signals that arrived meanwhile cause exactly one follow-up.
    expect(pending).toHaveLength(2);
    await settle(1, 'second');
    expect(screen.getByText('a:second')).toBeInTheDocument();
    expect(pending).toHaveLength(2);
  });

  it('reloads once per signal when nothing is in flight', async () => {
    render(<Probe id="a" />);
    await settle(0, 'one');
    act(() => signal());
    expect(pending).toHaveLength(2);
    await settle(1, 'two');
    act(() => signal());
    expect(pending).toHaveLength(3);
  });

  it('drops the old data as soon as the dependencies change, and ignores a late answer for the old ones', async () => {
    const view = render(<Probe id="a" />);
    await settle(0, 'data for a');
    expect(screen.getByText('a:data for a')).toBeInTheDocument();

    act(() => signal()); // a refresh for "a" is now in flight
    expect(pending).toHaveLength(2);
    view.rerender(<Probe id="b" />);
    expect(screen.getByText('b:loading')).toBeInTheDocument(); // not "b:data for a"

    await settle(1, 'late answer for a');
    expect(screen.getByText('b:loading')).toBeInTheDocument(); // the stale answer is not shown under b
    expect(pending).toHaveLength(3); // and b's own request starts once the old one is out of the way
    await settle(2, 'data for b');
    expect(screen.getByText('b:data for b')).toBeInTheDocument();
  });

  it('keeps the last good data when a refresh fails, and reports the error', async () => {
    render(<Probe id="a" />);
    await settle(0, 'good');
    act(() => signal());
    await act(async () => {
      pending[1].reject(new Error('backend down'));
      await Promise.resolve();
    });
    expect(screen.getByText('a:good error=backend down')).toBeInTheDocument();
  });

  it('unsubscribes and starts nothing after unmount', async () => {
    const view = render(<Probe id="a" />);
    expect(subscribers).toBe(1);
    act(() => signal()); // marks the in-flight request as stale
    view.unmount();
    expect(subscribers).toBe(0);
    await act(async () => {
      pending[0].resolve('too late');
      await Promise.resolve();
    });
    expect(pending).toHaveLength(1); // no follow-up request from an unmounted component
  });
});
