const API_BASE =
  import.meta.env.VITE_API_BASE?.replace(/\/$/, "") || "http://127.0.0.1:8765";

export type AppStatus = {
  voice_active: boolean;
  gesture_active: boolean;
  voice_recording: boolean;
  last_gesture: string;
  dominant_hand: "left" | "right";
};

export type DashboardSystemStatus = {
  voice_recognition_percent: number;
  gesture_detection_percent: number;
  cpu_utilization_percent: number;
  memory_usage_percent: number;
};

export type DashboardData = {
  voice_commands: number;
  gestures_detected: number;
  successful_actions: number;
  response_time_ms: number | null;
  recent_activity: Array<{
    time: string;
    action: string;
    type: string;
    status: string;
  }>;
  system_status: DashboardSystemStatus;
};

export async function fetchStatus(): Promise<AppStatus> {
  const res = await fetch(`${API_BASE}/api/status`);
  if (!res.ok) throw new Error("Failed to fetch status");
  return res.json();
}

export async function fetchDashboard(): Promise<DashboardData> {
  const res = await fetch(`${API_BASE}/api/dashboard`);
  if (!res.ok) throw new Error("Failed to fetch dashboard");
  return res.json();
}

export async function fetchUserName(): Promise<string> {
  const res = await fetch(`${API_BASE}/api/user`);
  if (!res.ok) throw new Error("Failed to fetch user name");
  const data = (await res.json()) as { name: string };
  return data.name;
}

export async function updateUserName(name: string): Promise<{ name: string }> {
  const res = await fetch(`${API_BASE}/api/user`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  if (!res.ok) throw new Error("Failed to update user name");
  return res.json();
}

export type VoiceChatHistoryMessage = {
  role: "user" | "system";
  text: string;
  timestamp: string;
};

export async function fetchVoiceChatHistory(): Promise<{ messages: VoiceChatHistoryMessage[] }> {
  const res = await fetch(`${API_BASE}/api/voice/chat-history`);
  if (!res.ok) throw new Error("Failed to fetch voice chat history");
  return res.json();
}

export async function startVoice(language: "EN" | "CN", duration = 5) {
  const res = await fetch(`${API_BASE}/api/voice/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ language, duration }),
  });
  return res.json();
}

export async function startGesture() {
  const res = await fetch(`${API_BASE}/api/gesture/start`, { method: "POST" });
  return res.json();
}

export async function stopGesture() {
  const res = await fetch(`${API_BASE}/api/gesture/stop`, { method: "POST" });
  return res.json();
}

export async function setGestureDominantHand(hand: "left" | "right") {
  const res = await fetch(`${API_BASE}/api/gesture/dominant-hand`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ hand }),
  });
  if (!res.ok) throw new Error("Failed to set dominant hand");
  return res.json();
}

const PREVIEW_FRAME_PREFIX = 0x01;

export function connectWebSocket(
  onMessage: (event: string, data: Record<string, unknown>) => void,
  onPreviewFrame?: (jpeg: Blob) => void,
): WebSocket {
  const previewParam = onPreviewFrame ? "?preview=1" : "";
  const wsUrl = API_BASE.replace(/^http/, "ws") + "/ws" + previewParam;
  const ws = new WebSocket(wsUrl);
  ws.binaryType = "arraybuffer";

  ws.onmessage = (ev) => {
    if (onPreviewFrame && (ev.data instanceof ArrayBuffer || ev.data instanceof Blob)) {
      const handleBuffer = (buffer: ArrayBuffer) => {
        const bytes = new Uint8Array(buffer);
        if (bytes.length < 2 || bytes[0] !== PREVIEW_FRAME_PREFIX) return;
        onPreviewFrame(new Blob([bytes.slice(1)], { type: "image/jpeg" }));
      };
      if (ev.data instanceof ArrayBuffer) {
        handleBuffer(ev.data);
        return;
      }
      ev.data.arrayBuffer().then(handleBuffer).catch(() => undefined);
      return;
    }

    if (typeof ev.data !== "string") return;

    try {
      const parsed = JSON.parse(ev.data) as {
        event: string;
        data: Record<string, unknown>;
      };
      onMessage(parsed.event, parsed.data || {});
    } catch {
      /* ignore malformed */
    }
  };
  return ws;
}

export function formatRelativeTime(iso: string): string {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return iso;
  const diffSec = Math.floor((Date.now() - then) / 1000);
  if (diffSec < 60) return `${diffSec} sec ago`;
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)} min ago`;
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)} hr ago`;
  return new Date(iso).toLocaleString();
}
