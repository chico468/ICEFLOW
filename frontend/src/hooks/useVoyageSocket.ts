/**
 * The live voyage: create it over REST, then sail it over a WebSocket.
 *
 * Creation runs the full route optimisation on the server and takes 15 to 25 seconds, so
 * the hook reports a `creating` phase with an elapsed clock rather than blocking. The
 * socket then pushes `state`, `tick`, `alert`, `paused`, `reroute` and `done` frames,
 * which are folded into the Zustand store.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { createVoyage, voyageSocketUrl } from '../api/client';
import type {
  CreateVoyageRequest,
  VoyageSocketAction,
  VoyageSocketFrame,
  VoyageState,
} from '../api/types';
import { useAppStore } from '../store/useAppStore';

export interface VoyageController {
  begin: (req: CreateVoyageRequest) => Promise<void>;
  play: () => void;
  pause: () => void;
  step: () => void;
  reroute: () => void;
  disconnect: () => void;
  elapsedMs: number;
  connected: boolean;
}

export function useVoyageSocket(): VoyageController {
  const socketRef = useRef<WebSocket | null>(null);
  const [connected, setConnected] = useState(false);
  const [elapsedMs, setElapsedMs] = useState(0);
  const timerRef = useRef<number | null>(null);

  const setVoyage = useAppStore((s) => s.setVoyage);
  const setVoyagePhase = useAppStore((s) => s.setVoyagePhase);
  const pushTick = useAppStore((s) => s.pushTick);
  const pushAlert = useAppStore((s) => s.pushAlert);

  const stopTimer = useCallback(() => {
    if (timerRef.current !== null) {
      window.clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const send = useCallback((action: VoyageSocketAction) => {
    const ws = socketRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(action));
  }, []);

  const openSocket = useCallback(
    (voyageId: string) => {
      const ws = new WebSocket(voyageSocketUrl(voyageId));
      socketRef.current = ws;
      setVoyagePhase('connecting');

      ws.onopen = () => {
        setConnected(true);
        // A button labelled "Start voyage" has to start the voyage.
        //
        // Creating the voyage and opening the socket used to leave the ship sitting at the
        // departure point until the operator found the separate Play control. After a 30-second
        // wait for the optimisation, that reads as a hang rather than as a step completing, and
        // in testing the interface it looked exactly like a broken socket. Ticking now begins as
        // soon as the socket is up; Pause and Step behave as before.
        setVoyagePhase('running');
        ws.send(
          JSON.stringify({
            action: 'start',
            tick_hours: useAppStore.getState().tickHours,
            interval_ms: useAppStore.getState().intervalMs,
          }),
        );
      };

      ws.onmessage = (event: MessageEvent<string>) => {
        let frame: VoyageSocketFrame;
        try {
          frame = JSON.parse(event.data) as VoyageSocketFrame;
        } catch {
          return;
        }
        switch (frame.type) {
          case 'state':
            setVoyage(frame.payload);
            break;
          case 'tick':
            pushTick(frame.payload);
            // A tick is proof the stream is live, whatever the phase said before.
            if (useAppStore.getState().voyagePhase !== 'running') setVoyagePhase('running');
            break;
          case 'alert':
            pushAlert(frame.payload);
            break;
          case 'paused':
            setVoyagePhase('paused');
            break;
          case 'reroute': {
            // The engine re-planned; adopt the new planned route in place.
            const summary = frame.payload;
            const current = useAppStore.getState().voyage;
            if (current) {
              const next: VoyageState = {
                ...current,
                planned_route: summary.waypoints,
                plan_summary: summary,
                reroute_count: current.reroute_count + 1,
              };
              useAppStore.setState({ voyage: next });
            }
            break;
          }
          case 'done':
            setVoyagePhase('done');
            break;
          case 'error':
            setVoyagePhase('error', frame.payload.message);
            break;
          default:
            break;
        }
      };

      ws.onerror = () => {
        setVoyagePhase('error', 'The voyage socket reported an error.');
      };

      ws.onclose = () => {
        setConnected(false);
        socketRef.current = null;
      };
    },
    [pushAlert, pushTick, setVoyage, setVoyagePhase],
  );

  const begin = useCallback(
    async (req: CreateVoyageRequest) => {
      socketRef.current?.close();
      useAppStore.getState().resetVoyage();
      setVoyagePhase('creating');
      setElapsedMs(0);
      const started = performance.now();
      stopTimer();
      timerRef.current = window.setInterval(() => setElapsedMs(performance.now() - started), 100);
      try {
        const state = await createVoyage(req);
        setVoyage(state);
        openSocket(state.voyage_id);
      } catch (err) {
        setVoyagePhase('error', err instanceof Error ? err.message : 'Voyage creation failed.');
      } finally {
        stopTimer();
      }
    },
    [openSocket, setVoyage, setVoyagePhase, stopTimer],
  );

  const play = useCallback(() => {
    const { tickHours, intervalMs } = useAppStore.getState();
    send({ action: 'start', tick_hours: tickHours, interval_ms: intervalMs });
    setVoyagePhase('running');
  }, [send, setVoyagePhase]);

  const pause = useCallback(() => {
    send({ action: 'pause' });
  }, [send]);

  const step = useCallback(() => {
    const { tickHours } = useAppStore.getState();
    send({ action: 'step', tick_hours: tickHours });
  }, [send]);

  const reroute = useCallback(() => {
    send({ action: 'reroute' });
  }, [send]);

  const disconnect = useCallback(() => {
    send({ action: 'close' });
    socketRef.current?.close();
    socketRef.current = null;
    setConnected(false);
  }, [send]);

  useEffect(
    () => () => {
      stopTimer();
      socketRef.current?.close();
      socketRef.current = null;
    },
    [stopTimer],
  );

  return { begin, play, pause, step, reroute, disconnect, elapsedMs, connected };
}
