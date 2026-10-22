/**
 * Which sea-ice display modes the data can actually support, and how missing cells are told apart from zero.
 * Pure (no imports), so it can be tested without a browser.
 *
 * Two rules drive this file:
 *  1. A mode is offered only when its data exists. Thickness is not shown when no thickness was returned;
 *     change is not shown without a second field on the very same grid to subtract. The reason is given, so
 *     a disabled control says why instead of just being dead.
 *  2. A missing value is not zero. Zero concentration is a real measurement ("open water"); a missing cell
 *     is the absence of one, and the chart paints and the legend names it separately.
 */

export type IceModeId = 'concentration' | 'classes' | 'thickness' | 'change';

type Grid = (number | null | undefined)[][];

export interface IceFieldLike {
  lats: number[];
  lons: number[];
  concentration?: Grid;
  thickness_m?: Grid;
}

export interface ModeAvailability {
  available: boolean;
  /** Why a mode is unavailable (or pending). Null when it is available. */
  reason: string | null;
}

/** Rows of a grid, or none if it is not an array of arrays. Malformed input is "no data", never an exception. */
function rowsOf(grid: unknown): unknown[][] {
  return Array.isArray(grid) ? grid.filter((r): r is unknown[] => Array.isArray(r)) : [];
}

/**
 * Is this a usable ice field: two or more finite latitudes and longitudes? The service should always send one,
 * but a response is data from outside the program, and this check is what keeps a malformed one from throwing
 * inside a render or a draw loop. Everything that reads an ice field asks this first.
 */
export function isUsableIceField(f: unknown): f is IceFieldLike {
  if (!f || typeof f !== 'object') return false;
  const { lats, lons } = f as { lats?: unknown; lons?: unknown };
  const axis = (a: unknown): boolean => Array.isArray(a) && a.length >= 2 && a.every((x) => typeof x === 'number' && Number.isFinite(x));
  return axis(lats) && axis(lons);
}

export function isMissing(v: unknown): boolean {
  return v === null || v === undefined || typeof v !== 'number' || !Number.isFinite(v);
}

export function countMissing(grid: Grid | undefined): { missing: number; total: number } {
  let missing = 0;
  let total = 0;
  for (const row of rowsOf(grid)) {
    for (const v of row) {
      total += 1;
      if (isMissing(v)) missing += 1;
    }
  }
  return { missing, total };
}

export function hasFinite(grid: Grid | undefined): boolean {
  for (const row of rowsOf(grid)) for (const v of row) if (!isMissing(v)) return true;
  return false;
}

export function sameGrid(a: IceFieldLike, b: IceFieldLike): boolean {
  return (
    a.lats.length === b.lats.length &&
    a.lons.length === b.lons.length &&
    a.lats[0] === b.lats[0] &&
    a.lons[0] === b.lons[0] &&
    a.lats[a.lats.length - 1] === b.lats[b.lats.length - 1] &&
    a.lons[a.lons.length - 1] === b.lons[b.lons.length - 1]
  );
}

export interface BaseState {
  field: IceFieldLike | null;
  loading: boolean;
  error: string | null;
}

export function modeAvailability(
  field: IceFieldLike | null,
  leadHours: number,
  base: BaseState,
): Record<IceModeId, ModeAvailability> {
  const none = (reason: string): ModeAvailability => ({ available: false, reason });
  const ok: ModeAvailability = { available: true, reason: null };

  if (!field) {
    const r = none('No ice field is loaded.');
    return { concentration: r, classes: r, thickness: r, change: r };
  }
  if (!isUsableIceField(field)) {
    const r = none('The ice field response is malformed and cannot be shown.');
    return { concentration: r, classes: r, thickness: r, change: r };
  }

  const conc = hasFinite(field.concentration) ? ok : none('This ice field has no concentration values.');
  const thickness = hasFinite(field.thickness_m) ? ok : none('This ice field has no thickness data, so thickness is not shown.');

  let change: ModeAvailability;
  if (!conc.available) change = none('Change needs concentration values, which are missing.');
  else if (leadHours <= 0) change = none('Choose a forecast time after +0 h: change compares that time with +0 h.');
  else if (base.error) change = none(`The +0 h field to compare with could not be loaded: ${base.error}`);
  else if (base.loading) change = none('Loading the +0 h field to compare with…');
  else if (!base.field) change = none('No +0 h field is available to compare with.');
  else if (!isUsableIceField(base.field) || !sameGrid(field, base.field)) change = none('The +0 h field is on a different grid, so the two cannot be subtracted.');
  else if (!hasFinite(base.field.concentration)) change = none('The +0 h field has no concentration values.');
  else change = ok;

  return { concentration: conc, classes: conc, thickness, change };
}
