import { useEffect, useState } from "react";
import { LIVE_POLL_MS, LIVE_URL, fetchLiveSnapshot } from "../api/fetchLive";
import type { LiveDeviceSnapshot } from "../types/status";

export interface UseLiveDeviceResult {
  snapshot: LiveDeviceSnapshot | null;
  error: string | null;
  isRefreshing: boolean;
}

export function useLiveDevice(
  url: string = LIVE_URL,
  intervalMs: number = LIVE_POLL_MS,
): UseLiveDeviceResult {
  const [snapshot, setSnapshot] = useState<LiveDeviceSnapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isRefreshing, setIsRefreshing] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const abort = new AbortController();

    const scheduleNext = () => {
      timer = setTimeout(() => {
        void load();
      }, intervalMs);
    };

    const load = async () => {
      if (cancelled) return;
      setIsRefreshing(true);
      try {
        const next = await fetchLiveSnapshot(url, abort.signal);
        if (cancelled) return;
        setSnapshot(next);
        setError(next.error);
      } catch (err) {
        if (
          cancelled ||
          (err instanceof DOMException && err.name === "AbortError")
        ) {
          return;
        }
        setError(
          err instanceof Error ? err.message : "Failed to fetch live snapshot",
        );
      } finally {
        if (!cancelled) {
          setIsRefreshing(false);
          scheduleNext();
        }
      }
    };

    void load();

    return () => {
      cancelled = true;
      abort.abort();
      if (timer !== undefined) clearTimeout(timer);
    };
  }, [url, intervalMs]);

  return { snapshot, error, isRefreshing };
}
