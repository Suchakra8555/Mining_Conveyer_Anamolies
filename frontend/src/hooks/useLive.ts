import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";

/** Optional WebSocket push: on an "update" message, refetch everything. Polling (useApi.ts) keeps working if the socket is down. */
export function useLive() {
  const qc = useQueryClient();
  useEffect(() => {
    let ws: WebSocket | null = null, timer: number | undefined, closed = false, last = 0;
    const open = () => {
      try {
        ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/ws`);
        ws.onmessage = () => { const now = Date.now(); if (now - last > 800) { last = now; qc.invalidateQueries(); } };
        ws.onclose = () => { if (!closed) timer = window.setTimeout(open, 3000); };   // reconnect; polling covers the gap
      } catch { /* polling only */ }
    };
    open();
    return () => { closed = true; clearTimeout(timer); ws?.close(); };
  }, [qc]);
}
