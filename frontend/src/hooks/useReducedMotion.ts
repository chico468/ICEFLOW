/**
 * The user's reduced-motion preference, kept current if they change it while the app is open.
 * Shared so every animated thing (map transitions, flow particles) reads the same source.
 */
import { useEffect, useState } from 'react';

const QUERY = '(prefers-reduced-motion: reduce)';

export function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(() => window.matchMedia?.(QUERY).matches ?? false);
  useEffect(() => {
    const mq = window.matchMedia?.(QUERY);
    if (!mq) return undefined;
    const on = (): void => setReduced(mq.matches);
    on();
    mq.addEventListener('change', on);
    return () => mq.removeEventListener('change', on);
  }, []);
  return reduced;
}
