import { useCallback } from "react";
import { useNavigate } from "react-router";
import { fetchStatus, startGesture } from "../lib/api";
import { isCompactModeActive, isCompactWindow } from "../lib/desktop";

const AUTO_START_VOICE = "friday:auto-start-voice";
const AUTO_START_GESTURE = "friday:auto-start-gesture";

async function waitForModuleIdle(target: "voice" | "gesture"): Promise<void> {
  for (let i = 0; i < 40; i += 1) {
    try {
      const status = await fetchStatus();
      if (target === "voice" && !status.gesture_active) return;
      if (target === "gesture" && !status.voice_active) return;
    } catch {
      /* retry */
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
}

async function shouldHandleModuleSwitch(): Promise<boolean> {
  if (isCompactWindow()) return true;
  return !(await isCompactModeActive());
}

function routeForTarget(target: "voice" | "gesture"): string {
  const compact = isCompactWindow();
  if (target === "voice") return compact ? "/compact/voice" : "/voice";
  return compact ? "/compact/gesture" : "/gesture";
}

/** Handler to merge into an existing WebSocket listener (avoids extra connections). */
export function useModuleSwitchHandler() {
  const navigate = useNavigate();

  return useCallback(
    (event: string, data: Record<string, unknown>) => {
      if (event !== "module.switch") return;

      void (async () => {
        if (!(await shouldHandleModuleSwitch())) return;

        const target = String(data.target || "");
        const autoStart = Boolean(data.auto_start);
        if (target !== "voice" && target !== "gesture") return;

        await waitForModuleIdle(target as "voice" | "gesture");
        navigate(routeForTarget(target as "voice" | "gesture"));

        if (!autoStart) return;

        await new Promise((resolve) => setTimeout(resolve, 200));

        if (target === "gesture") {
          try {
            const status = await fetchStatus();
            if (!status.gesture_active) {
              await startGesture();
            }
          } catch {
            /* GestureControl syncs UI from gesture.started / status on mount */
          }
          return;
        }

        window.dispatchEvent(new CustomEvent(AUTO_START_VOICE));
      })();
    },
    [navigate],
  );
}

export { AUTO_START_VOICE, AUTO_START_GESTURE };
