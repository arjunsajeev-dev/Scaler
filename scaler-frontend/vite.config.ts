import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import { mqttLiveBridge } from "./server/mqttBridge";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");

  return {
    plugins: [
      react(),
      mqttLiveBridge({
        brokerUrl: env.MQTT_URL || undefined,
        deviceId: env.MQTT_DEVICE_ID || env.VITE_DEVICE_ID || undefined,
      }),
    ],
    server: {
      host: "127.0.0.1",
      port: 5173,
    },
  };
});
