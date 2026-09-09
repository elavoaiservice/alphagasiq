"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { useAuth } from "./auth-context";

// Mirrors `packages/schemas/schemas/events.py`'s `DomainEvent` -- only the fields
// `GET /ws/events` (apps/api/api_app/routers/ws.py) actually forwards.
export interface LiveDomainEvent {
  event_id: string;
  event_type: string;
  occurred_at: string;
  payload: Record<string, unknown>;
}

type Listener = (event: LiveDomainEvent) => void;

interface LiveEventsState {
  connected: boolean;
  subscribe: (listener: Listener) => () => void;
}

const LiveEventsContext = createContext<LiveEventsState | null>(null);

const WS_BASE = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1").replace(/^http/, "ws");

// Event types worth surfacing as a toast on every dashboard page, independent of
// whatever a specific page's own `subscribe` callback does with them.
const TOAST_EVENT_TYPES = new Set(["SIGNAL_ESCALATED", "TRADE_APPROVED", "TRADE_REJECTED", "RISK_LIMIT_BREACHED"]);

function toastText(event: LiveDomainEvent): string {
  const headline = event.payload.headline;
  if (typeof headline === "string") return headline;
  return event.event_type.replace(/_/g, " ").toLowerCase();
}

/** Owns the single `GET /ws/events` connection for the whole authenticated session --
 * mounted once in `app/platform/layout.tsx` so every dashboard page shares it via
 * `useLiveEvents()` rather than each page opening its own socket. Auto-reconnects
 * with exponential backoff on close/error (a dropped connection is expected on
 * laptop-sleep/network-change, not a bug to surface to the user beyond the small
 * status indicator below). */
export function LiveEventsProvider({ children }: { children: React.ReactNode }) {
  const { token } = useAuth();
  const [connected, setConnected] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const listenersRef = useRef<Set<Listener>>(new Set());

  useEffect(() => {
    if (!token) return undefined;
    let socket: WebSocket | null = null;
    let stopped = false;
    let retryDelayMs = 1000;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let toastTimer: ReturnType<typeof setTimeout> | null = null;

    function connect() {
      socket = new WebSocket(`${WS_BASE}/ws/events?token=${encodeURIComponent(token!)}`);

      socket.onopen = () => {
        retryDelayMs = 1000;
        setConnected(true);
      };

      socket.onmessage = (evt: MessageEvent<string>) => {
        let parsed: LiveDomainEvent;
        try {
          parsed = JSON.parse(evt.data);
        } catch {
          return;
        }
        listenersRef.current.forEach((listener) => listener(parsed));
        if (TOAST_EVENT_TYPES.has(parsed.event_type)) {
          setToast(toastText(parsed));
          if (toastTimer) clearTimeout(toastTimer);
          toastTimer = setTimeout(() => setToast(null), 6000);
        }
      };

      socket.onclose = () => {
        setConnected(false);
        if (stopped) return;
        retryTimer = setTimeout(connect, retryDelayMs);
        retryDelayMs = Math.min(retryDelayMs * 2, 30000);
      };

      socket.onerror = () => {
        socket?.close();
      };
    }

    connect();
    return () => {
      stopped = true;
      if (retryTimer) clearTimeout(retryTimer);
      if (toastTimer) clearTimeout(toastTimer);
      socket?.close();
    };
  }, [token]);

  const subscribe = useCallback((listener: Listener) => {
    listenersRef.current.add(listener);
    return () => {
      listenersRef.current.delete(listener);
    };
  }, []);

  return (
    <LiveEventsContext.Provider value={{ connected, subscribe }}>
      {children}
      <div className="fixed bottom-2 right-2 z-50 flex flex-col items-end gap-1">
        {toast && (
          <div className="rounded border border-terminal-border bg-terminal-panel px-3 py-2 text-xs shadow-lg">
            {toast}
          </div>
        )}
        {token && (
          <div className="text-[10px] text-terminal-muted">{connected ? "● live" : "○ reconnecting…"}</div>
        )}
      </div>
    </LiveEventsContext.Provider>
  );
}

/** Subscribe to every live event forwarded over `GET /ws/events`, already filtered
 * server-side to what the current caller may see. Returns `connected` (for a
 * page-local indicator, if wanted) and `subscribe`, whose returned function must be
 * called on cleanup (see `SignalsTable.tsx` for the worked example). */
export function useLiveEvents(): LiveEventsState {
  const ctx = useContext(LiveEventsContext);
  if (!ctx) throw new Error("useLiveEvents must be used within LiveEventsProvider");
  return ctx;
}

/** Re-run `reload` whenever one of `eventTypes` arrives.
 *
 * Most dashboard tables want "something changed server-side, fetch again" rather
 * than SignalsTable's optimistic prepend: the WebSocket payload for a trade
 * approval or a consensus update is not the same shape as the table's own row, so
 * refetching is both simpler and guaranteed consistent with the REST view.
 *
 * `reload` is kept in a ref, so a caller can pass an inline closure without
 * resubscribing on every render.
 */
export function useLiveRefetch(eventTypes: string[], reload: () => void): void {
  const { subscribe } = useLiveEvents();
  const reloadRef = useRef(reload);
  reloadRef.current = reload;
  // Join, so a caller passing a fresh array literal each render doesn't resubscribe.
  const key = eventTypes.join(",");

  useEffect(() => {
    const wanted = new Set(key.split(",").filter(Boolean));
    return subscribe((event) => {
      if (wanted.has(event.event_type)) reloadRef.current();
    });
  }, [subscribe, key]);
}
