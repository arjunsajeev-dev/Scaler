import type { LiveDeviceSnapshot } from "../types/status";

export const LIVE_POLL_MS = 5_000;
export const LIVE_URL = "/api/live";

export async function fetchLiveSnapshot(
  url: string = LIVE_URL,
  signal?: AbortSignal,
): Promise<LiveDeviceSnapshot> {
  const response = await fetch(url, {
    method: "GET",
    headers: { Accept: "application/json" },
    cache: "no-store",
    signal,
  });

  if (!response.ok) {
    throw new Error(`Live snapshot fetch failed (${response.status})`);
  }

  return (await response.json()) as LiveDeviceSnapshot;
}
