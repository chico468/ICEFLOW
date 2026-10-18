/**
 * Whether the surrounding screen is the one on display.
 *
 * App keeps every screen mounted and hides the inactive ones with `visibility: hidden`, which
 * does not stop a requestAnimationFrame loop and is not reliably reported by IntersectionObserver. Anything
 * that animates continuously therefore asks this context before it does any work, rather than guessing.
 * The default is true so a component rendered outside App (a test, a story) still runs.
 */
import { createContext, useContext } from 'react';

export const ScreenActiveContext = createContext<boolean>(true);

export function useScreenActive(): boolean {
  return useContext(ScreenActiveContext);
}
