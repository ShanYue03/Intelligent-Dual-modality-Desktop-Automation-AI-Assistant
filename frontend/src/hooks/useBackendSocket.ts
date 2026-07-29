import { useEffect, useRef } from "react";
import { connectWebSocket } from "../lib/api";

type Handler = (event: string, data: Record<string, unknown>) => void;
type FrameHandler = (jpeg: Blob) => void;

export function useBackendSocket(onEvent: Handler, onPreviewFrame?: FrameHandler) {
  const handlerRef = useRef(onEvent);
  handlerRef.current = onEvent;
  const frameHandlerRef = useRef(onPreviewFrame);
  frameHandlerRef.current = onPreviewFrame;

  useEffect(() => {
    let ws: WebSocket | null = null;
    let closed = false;
    let retryTimer: ReturnType<typeof setTimeout>;

    const connect = () => {
      if (closed) return;
      ws = connectWebSocket(
        (event, data) => handlerRef.current(event, data),
        frameHandlerRef.current
          ? (jpeg) => frameHandlerRef.current?.(jpeg)
          : undefined,
      );
      ws.onclose = () => {
        if (!closed) retryTimer = setTimeout(connect, 2000);
      };
    };

    connect();
    return () => {
      closed = true;
      clearTimeout(retryTimer);
      ws?.close();
    };
  }, []);
}
