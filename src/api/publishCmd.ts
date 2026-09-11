import type { DeviceCommand } from "../types/status";

export async function publishDeviceCommand(
  command: DeviceCommand,
): Promise<void> {
  const response = await fetch("/api/cmd", {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify(command),
  });

  if (!response.ok) {
    let detail = `Command publish failed (${response.status})`;
    try {
      const body = (await response.json()) as { error?: string };
      if (body.error) detail = body.error;
    } catch {
      // keep status text
    }
    throw new Error(detail);
  }
}
