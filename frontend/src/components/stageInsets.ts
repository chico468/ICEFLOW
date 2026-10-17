/**
 * How much of the map's edges are covered by floating panels, in CSS pixels.
 *
 * Lives in its own tiny module so the map layer can read it without importing the stage
 * component, which itself renders UI primitives (that would be a circular import).
 */
import { createContext, useContext } from 'react';

export interface StageInsets {
  left: number;
  right: number;
  top: number;
  bottom: number;
}

export const NO_INSETS: StageInsets = { left: 0, right: 0, top: 0, bottom: 0 };

export const StageInsetsContext = createContext<StageInsets>(NO_INSETS);

export function useStageInsets(): StageInsets {
  return useContext(StageInsetsContext);
}
