'use client';

import { useEffect, useRef } from 'react';

type Options = {
  enabled?: boolean;
  immediate?: boolean;
  intervalMs: number;
  pauseWhenHidden?: boolean;
  onTick: () => void | Promise<void>;
};

export function useAdaptivePolling({
  enabled = true,
  immediate = true,
  intervalMs,
  pauseWhenHidden = true,
  onTick,
}: Options): void {
  const onTickRef = useRef(onTick);

  useEffect(() => {
    onTickRef.current = onTick;
  }, [onTick]);

  useEffect(() => {
    if (!enabled) {
      return;
    }

    if (immediate && (!pauseWhenHidden || !document.hidden)) {
      void onTickRef.current();
    }

    const run = () => {
      if (pauseWhenHidden && document.hidden) {
        return;
      }
      void onTickRef.current();
    };

    const interval = window.setInterval(run, intervalMs);
    const onVisible = () => {
      if (!pauseWhenHidden || !document.hidden) {
        void onTickRef.current();
      }
    };

    document.addEventListener('visibilitychange', onVisible);
    return () => {
      window.clearInterval(interval);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [enabled, immediate, intervalMs, pauseWhenHidden]);
}
