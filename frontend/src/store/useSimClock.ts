/**
 * Sim clock store: drives the voyage bridge clock.
 *
 * Starts at the first timeline t_utc. Speeds: 1x / 60x / 600x / 3600x. Pause, seek slider.
 * The store holds the wall-clock-derived sim position; consumers (PositionSource, panels)
 * read from it.
 */
import { create } from 'zustand';
import type { TimelinePoint } from '../lib/timeline.ts';

export interface SimClockState {
  timeline: TimelinePoint[];
  simMs: number; // wall-clock ms elapsed at 1x
  speed: number; // 1 | 60 | 600 | 3600
  paused: boolean;
  setTimeline: (tl: TimelinePoint[]) => void;
  setSimMs: (ms: number) => void;
  setSpeed: (s: number) => void;
  setPaused: (p: boolean) => void;
  seekHours: (h: number) => void;
  reset: () => void;
}

const SPEEDS = [1, 60, 600, 3600] as const;

export const useSimClock = create<SimClockState>((set) => ({
  timeline: [],
  simMs: 0,
  speed: 1,
  paused: true,
  setTimeline: (tl) => set({ timeline: tl, simMs: 0, paused: true }),
  setSimMs: (ms) => set({ simMs: ms }),
  setSpeed: (s) => set({ speed: s }),
  setPaused: (p) => set({ paused: p }),
  seekHours: (h) => set({ simMs: h * 3600 * 1000 }),
  reset: () => set({ timeline: [], simMs: 0, speed: 1, paused: true }),
}));

export const SPEED_LABELS: Record<number, string> = {
  1: '1×',
  60: '60×',
  600: '600×',
  3600: '3600×',
};

export function isValidSpeed(s: number): s is (typeof SPEEDS)[number] {
  return (SPEEDS as readonly number[]).includes(s);
}
