/**
 * Whether the last progress or chapter request failed without a response.
 * Lets the reader say "server unreachable" even while navigator.onLine is true.
 */
type Listener = (unreachable: boolean) => void;

const listeners = new Set<Listener>();
let unreachable = false;

export const isServerUnreachable = () => unreachable;

const setUnreachable = (value: boolean) => {
  if (value === unreachable) return;
  unreachable = value;
  listeners.forEach((listener) => listener(value));
};

export const markServerUnreachable = () => setUnreachable(true);
export const markServerReachable = () => setUnreachable(false);

export const subscribeServerReachability = (listener: Listener): (() => void) => {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
};
