"use client";

import { useEffect, useState } from "react";

const API_BASE =
  typeof window === "undefined"
    ? (process.env["API_BASE_URL"] ?? "http://localhost:8000")
    : "";

type ChangeEvent = {
  id: string;
  source_id: string;
  document_id: string;
  title: string;
  url: string | null;
  detected_at: string;
  change_type: string;
  domain: string;
  severity: "high" | "medium" | "low";
  summary: string | null;
  read: boolean;
};

type ChangesResponse = {
  events: ChangeEvent[];
  total: number;
  unread_count: number;
};

const SEVERITY_CONFIG: Record<
  ChangeEvent["severity"],
  { bg: string; border: string; text: string; icon: string; label: string }
> = {
  high: {
    bg: "bg-red-50",
    border: "border-red-300",
    text: "text-red-800",
    icon: "🔴",
    label: "Alta prioridad",
  },
  medium: {
    bg: "bg-amber-50",
    border: "border-amber-300",
    text: "text-amber-800",
    icon: "🟡",
    label: "Prioridad media",
  },
  low: {
    bg: "bg-blue-50",
    border: "border-blue-200",
    text: "text-blue-800",
    icon: "🔵",
    label: "Baja prioridad",
  },
};

const SOURCE_LABELS: Record<string, string> = {
  boe: "BOE",
  eurlex: "EUR-Lex",
  cnmc: "CNMC",
  sepblac: "SEPBLAC",
  bcbs_bis: "BCBS/BIS",
  federal_register: "Federal Register",
  bcb_brasil: "BCB Brasil",
  bcra: "BCRA",
};

function formatRelativeDate(isoDate: string): string {
  const date = new Date(isoDate);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));
  if (diffDays === 0) return "hoy";
  if (diffDays === 1) return "ayer";
  if (diffDays < 7) return `hace ${diffDays} días`;
  return date.toLocaleDateString("es-ES", { day: "2-digit", month: "short" });
}

async function fetchUnreadChanges(): Promise<ChangesResponse | null> {
  const token =
    typeof window !== "undefined"
      ? sessionStorage.getItem("lex_agents_token")
      : null;

  try {
    const res = await fetch(
      `${API_BASE}/api/v1/monitoring/changes?unread_only=true&limit=10`,
      {
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        cache: "no-store",
      },
    );
    if (!res.ok) return null;
    return (await res.json()) as ChangesResponse;
  } catch {
    return null;
  }
}

async function markEventRead(eventId: string): Promise<void> {
  const token =
    typeof window !== "undefined"
      ? sessionStorage.getItem("lex_agents_token")
      : null;

  try {
    await fetch(`${API_BASE}/api/v1/monitoring/changes/${eventId}/read`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
    });
  } catch {
    // Best-effort
  }
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function ChangeAlertBanner() {
  const [events, setEvents] = useState<ChangeEvent[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const [expanded, setExpanded] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    fetchUnreadChanges().then((data) => {
      if (data && data.unread_count > 0) {
        setEvents(data.events);
        setUnreadCount(data.unread_count);
      }
      setLoaded(true);
    });
  }, []);

  if (!loaded || unreadCount === 0 || dismissed) return null;

  async function handleDismissAll() {
    for (const event of events) {
      await markEventRead(event.id);
    }
    setDismissed(true);
  }

  async function handleMarkRead(eventId: string) {
    await markEventRead(eventId);
    const updated = events.filter((e) => e.id !== eventId);
    setEvents(updated);
    setUnreadCount(updated.length);
    if (updated.length === 0) setDismissed(true);
  }

  const highCount = events.filter((e) => e.severity === "high").length;
  const bannerConfig =
    highCount > 0 ? SEVERITY_CONFIG.high : SEVERITY_CONFIG.medium;

  return (
    <div
      className={`rounded-lg border ${bannerConfig.border} ${bannerConfig.bg} px-4 py-3 text-sm`}
    >
      {/* Header row */}
      <div className="flex items-center justify-between gap-3">
        <div className={`flex items-center gap-2 font-medium ${bannerConfig.text}`}>
          <span>📋</span>
          <span>
            {unreadCount === 1
              ? "1 cambio normativo detectado"
              : `${unreadCount} cambios normativos detectados`}
            {highCount > 0 && (
              <span className="ml-2 inline-flex items-center rounded bg-red-100 px-1.5 py-0.5 text-xs font-medium text-red-700">
                {highCount} alta prioridad
              </span>
            )}
          </span>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <button
            onClick={() => setExpanded(!expanded)}
            className={`text-xs underline ${bannerConfig.text}`}
          >
            {expanded ? "Ocultar" : "Ver detalles"}
          </button>
          <button
            onClick={handleDismissAll}
            className={`text-xs ${bannerConfig.text} hover:opacity-70`}
            title="Marcar todo como leído"
          >
            ✕
          </button>
        </div>
      </div>

      {/* Expanded event list */}
      {expanded && (
        <ul className="mt-3 space-y-2">
          {events.map((event) => {
            const cfg = SEVERITY_CONFIG[event.severity];
            return (
              <li
                key={event.id}
                className="flex items-start justify-between gap-2"
              >
                <div className="flex items-start gap-2 min-w-0">
                  <span className="mt-0.5 shrink-0">{cfg.icon}</span>
                  <div className="min-w-0">
                    <span className={`font-medium ${bannerConfig.text}`}>
                      [{SOURCE_LABELS[event.source_id] ?? event.source_id}]{" "}
                    </span>
                    <span className={`${bannerConfig.text} truncate`}>
                      {event.document_id}
                    </span>
                    <span className="ml-2 text-xs text-muted-foreground">
                      {formatRelativeDate(event.detected_at)}
                    </span>
                    {event.url && (
                      <a
                        href={event.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className={`ml-2 text-xs underline ${bannerConfig.text}`}
                      >
                        ↗
                      </a>
                    )}
                  </div>
                </div>
                <button
                  onClick={() => handleMarkRead(event.id)}
                  className={`shrink-0 text-xs underline ${bannerConfig.text}`}
                  title="Marcar como leído"
                >
                  Leído
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
