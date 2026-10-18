import { useEffect, useRef, useState } from "react";

/** Eases a number towards its target every animation frame, so live figures glide instead of jumping. */
export function useTween(target: number | null | undefined, ms = 600): number | null {
  const [value, setValue] = useState<number | null>(target ?? null);
  const current = useRef<number | null>(target ?? null);
  useEffect(() => {
    if (target === null || target === undefined) {
      current.current = null;
      setValue(null);
      return;
    }
    if (current.current === null) {
      current.current = target;
      setValue(target);
      return;
    }
    let raf = 0;
    let last = performance.now();
    const step = (now: number) => {
      const dt = now - last;
      last = now;
      const k = 1 - Math.exp(-dt / (ms / 4));
      const next = current.current! + (target - current.current!) * k;
      current.current = Math.abs(target - next) < 0.05 ? target : next;
      setValue(current.current);
      if (current.current !== target) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [target, ms]);
  return value;
}
