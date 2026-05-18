"use client";

import { useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

const API_BASE =
  typeof window === "undefined"
    ? (process.env["API_BASE_URL"] ?? "http://localhost:8000")
    : "";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type CalendarEvent = {
  id: string;
  title: string;
  description: string | null;
  event_date: string;
  deadline_type: string;
  source_id: string;
  url: string | null;
  domain: string;
  jurisdiction: string;
  regulation_ref: string | null;
};

type CalendarResponse = {
  events: CalendarEvent[];
  total: int;
};

// Temporary workaround: the TS compiler doesn't know `int` — use number
type int = number;

// ---------------------------------------------------------------------------
// Constants (locale-independent)
// ---------------------------------------------------------------------------

const DEADLINE_TYPE_COLORS: Record<
  string,
  { color: string; bg: string; border: string }
> = {
  consultation: {
    color: "text-blue-800",
    bg: "bg-blue-50",
    border: "border-blue-200",
  },
  application: {
    color: "text-red-800",
    bg: "bg-red-50",
    border: "border-red-200",
  },
  reporting: {
    color: "text-amber-800",
    bg: "bg-amber-50",
    border: "border-amber-200",
  },
  review: {
    color: "text-purple-800",
    bg: "bg-purple-50",
    border: "border-purple-200",
  },
  publication: {
    color: "text-green-800",
    bg: "bg-green-50",
    border: "border-green-200",
  },
  other: {
    color: "text-gray-700",
    bg: "bg-gray-50",
    border: "border-gray-200",
  },
};

const SOURCE_LABELS: Record<string, string> = {
  eba_calendar: "EBA",
  eurlex: "EUR-Lex",
  boe: "BOE",
  esma: "ESMA",
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function parseDate(iso: string): Date {
  // event_date is "YYYY-MM-DD" — parse as local date to avoid UTC offset
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y!, m! - 1, d!);
}

function daysUntil(iso: string): number {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const target = parseDate(iso);
  return Math.round(
    (target.getTime() - today.getTime()) / (1000 * 60 * 60 * 24),
  );
}

function groupByMonth(events: CalendarEvent[]): [string, CalendarEvent[]][] {
  const groups = new Map<string, CalendarEvent[]>();
  for (const ev of events) {
    const d = parseDate(ev.event_date);
    const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
    const existing = groups.get(key) ?? [];
    existing.push(ev);
    groups.set(key, existing);
  }
  return Array.from(groups.entries()).sort(([a], [b]) => a.localeCompare(b));
}

// ---------------------------------------------------------------------------
// API calls
// ---------------------------------------------------------------------------

async function fetchEvents(
  days: number,
  filter: string,
): Promise<CalendarResponse | null> {
  const token =
    typeof window !== "undefined"
      ? sessionStorage.getItem("lex_agents_token")
      : null;

  const path =
    days > 0
      ? `/api/v1/calendar/events/upcoming?days=${days}`
      : `/api/v1/calendar/events?${filter ? `deadline_type=${filter}` : ""}`;

  try {
    const res = await fetch(`${API_BASE}${path}`, {
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
    });
    if (!res.ok) return null;
    return (await res.json()) as CalendarResponse;
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// Components
// ---------------------------------------------------------------------------

function DaysBadge({ iso }: { iso: string }) {
  const t = useTranslations("calendario");
  const n = daysUntil(iso);
  if (n < 0)
    return (
      <span className="text-[10px] text-muted-foreground">{t("past")}</span>
    );
  if (n === 0)
    return (
      <span className="text-[10px] font-semibold text-red-600 bg-red-50 px-1.5 py-0.5 rounded">
        {t("today")}
      </span>
    );
  if (n <= 7)
    return (
      <span className="text-[10px] font-semibold text-amber-700 bg-amber-50 px-1.5 py-0.5 rounded">
        {n}
        {t("daysUnit")}
      </span>
    );
  return (
    <span className="text-[10px] text-muted-foreground">
      {n}
      {t("daysUnit")}
    </span>
  );
}

function EventCard({ event }: { event: CalendarEvent }) {
  const t = useTranslations("calendario");
  const locale = useLocale();
  const cfg =
    DEADLINE_TYPE_COLORS[event.deadline_type] ?? DEADLINE_TYPE_COLORS["other"]!;

  const typeKey = `type${event.deadline_type.charAt(0).toUpperCase()}${event.deadline_type.slice(1)}`;
  const typeLabel = t(typeKey);

  const dateDisplay = parseDate(event.event_date).toLocaleDateString(locale, {
    day: "numeric",
    month: "long",
    year: "numeric",
  });

  return (
    <div
      className={`rounded-md border ${cfg.border} ${cfg.bg} px-4 py-3 space-y-1`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span
              className={`text-[10px] font-medium uppercase tracking-wide rounded px-1.5 py-0.5 ${cfg.color} ${cfg.bg} border ${cfg.border}`}
            >
              {typeLabel}
            </span>
            <span className="text-[10px] text-muted-foreground">
              {SOURCE_LABELS[event.source_id] ?? event.source_id}
            </span>
            {event.jurisdiction && event.jurisdiction !== "EU" && (
              <span className="text-[10px] font-mono text-muted-foreground">
                {event.jurisdiction}
              </span>
            )}
          </div>
          <p className={`mt-1 text-sm font-medium ${cfg.color} leading-snug`}>
            {event.url ? (
              <a
                href={event.url}
                target="_blank"
                rel="noopener noreferrer"
                className="hover:underline"
              >
                {event.title} ↗
              </a>
            ) : (
              event.title
            )}
          </p>
          {event.description && (
            <p className="text-xs text-muted-foreground mt-0.5 line-clamp-2">
              {event.description}
            </p>
          )}
          {event.regulation_ref && (
            <p className="text-[10px] font-mono text-muted-foreground mt-0.5">
              {event.regulation_ref}
            </p>
          )}
        </div>
        <div className="shrink-0 text-right space-y-0.5">
          <p className="text-xs font-medium text-foreground">{dateDisplay}</p>
          <DaysBadge iso={event.event_date} />
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function CalendarioPage() {
  const t = useTranslations("calendario");
  const locale = useLocale();
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [range, setRange] = useState(90);
  const [filter, setFilter] = useState("");

  const FILTER_OPTIONS = [
    { value: "", label: t("filterAll") },
    { value: "consultation", label: t("filterConsultation") },
    { value: "application", label: t("filterApplication") },
    { value: "reporting", label: t("filterReporting") },
    { value: "review", label: t("filterReview") },
    { value: "publication", label: t("filterPublication") },
  ];

  const RANGE_OPTIONS = [
    { value: 30, label: t("range30") },
    { value: 90, label: t("range90") },
    { value: 180, label: t("range180") },
    { value: 365, label: t("range365") },
    { value: 0, label: t("rangeAll") },
  ];

  useEffect(() => {
    setLoading(true);
    setError(null);
    fetchEvents(range, filter).then((data) => {
      if (!data) {
        setError(
          "No se pudo cargar el calendario. Asegúrese de estar autenticado.",
        );
      } else {
        setEvents(data.events);
      }
      setLoading(false);
    });
  }, [range, filter]);

  const grouped = groupByMonth(events);

  function monthLabel(key: string): string {
    const [y, m] = key.split("-").map(Number);
    const d = new Date(y!, m! - 1, 1);
    return d.toLocaleDateString(locale, { month: "long", year: "numeric" });
  }

  return (
    <div className="flex min-h-screen flex-col">
      <main className="flex-1 mx-auto w-full max-w-4xl px-4 py-8 space-y-6">
        <header className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">{t("title")}</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              {t("subtitle")}
            </p>
          </div>

          {/* Controls */}
          <div className="flex items-center gap-2 flex-wrap">
            {/* Range selector */}
            <select
              value={range}
              onChange={(e) => setRange(Number(e.target.value))}
              className="rounded border border-input bg-background px-2 py-1.5 text-xs"
            >
              {RANGE_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>

            {/* Type filter */}
            <div className="flex items-center gap-1 flex-wrap">
              {FILTER_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => setFilter(opt.value)}
                  className={[
                    "px-2.5 py-1 text-xs font-medium rounded-full border transition-colors",
                    filter === opt.value
                      ? "bg-primary text-primary-foreground border-primary"
                      : "bg-background text-muted-foreground border-input hover:bg-muted",
                  ].join(" ")}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>
        </header>

        {/* Loading / error / empty */}
        {loading && (
          <div className="flex items-center justify-center py-12">
            <p className="text-sm text-muted-foreground animate-pulse">
              {t("loading")}
            </p>
          </div>
        )}

        {!loading && error && (
          <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}

        {!loading && !error && events.length === 0 && (
          <div className="rounded-md border border-border bg-muted/30 px-6 py-10 text-center">
            <p className="text-sm text-muted-foreground">{t("noEvents")}</p>
            <p className="text-xs text-muted-foreground mt-1">
              {t("noEventsHint")}
            </p>
          </div>
        )}

        {/* Timeline grouped by month */}
        {!loading && !error && grouped.length > 0 && (
          <div className="space-y-8">
            {grouped.map(([monthKey, monthEvents]) => (
              <section key={monthKey}>
                <h2 className="text-xs font-semibold uppercase tracking-widest text-muted-foreground mb-3">
                  {monthLabel(monthKey)}
                  <span className="ml-2 normal-case font-normal">
                    ({t("monthEvents", { count: monthEvents.length })})
                  </span>
                </h2>
                <div className="space-y-2">
                  {monthEvents.map((ev) => (
                    <EventCard key={ev.id} event={ev} />
                  ))}
                </div>
              </section>
            ))}
          </div>
        )}

        {/* Summary bar */}
        {!loading && events.length > 0 && (
          <div className="border-t border-border pt-4 text-xs text-muted-foreground flex items-center justify-between">
            <span>{t("eventsCount", { count: events.length })}</span>
            <span className="font-mono">{t("footerSource")}</span>
          </div>
        )}
      </main>
    </div>
  );
}
