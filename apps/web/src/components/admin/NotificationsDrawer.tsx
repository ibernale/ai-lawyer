"use client";

import { useEffect, useState } from "react";
import {
  listNotifications,
  markNotificationRead,
  markAllNotificationsRead,
  type NotificationRow,
} from "@/lib/api";

type Filter = "all" | "critical" | "warning" | "info";

const CATEGORY_STYLES: Record<string, string> = {
  critical: "bg-red-100 text-red-800",
  warning: "bg-amber-100 text-amber-800",
  info: "bg-blue-100 text-blue-800",
};

function relativeTime(isoString: string): string {
  const diff = Date.now() - new Date(isoString + "Z").getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

export function NotificationsDrawer({
  onClose,
  onCountChange,
}: {
  onClose: () => void;
  onCountChange: (count: number) => void;
}) {
  const [notifications, setNotifications] = useState<NotificationRow[]>([]);
  const [filter, setFilter] = useState<Filter>("all");
  const [loading, setLoading] = useState(true);

  function refreshUnreadCount(rows: NotificationRow[]) {
    onCountChange(rows.filter((r) => r.read_at === null).length);
  }

  useEffect(() => {
    listNotifications()
      .then((rows) => {
        setNotifications(rows);
        refreshUnreadCount(rows);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function handleMarkRead(id: number) {
    await markNotificationRead(id).catch(() => {});
    setNotifications((prev) => {
      const updated = prev.map((n) =>
        n.id === id
          ? { ...n, read_at: new Date().toISOString(), read_by: "me" }
          : n,
      );
      refreshUnreadCount(updated);
      return updated;
    });
  }

  async function handleMarkAll() {
    await markAllNotificationsRead().catch(() => {});
    setNotifications((prev) => {
      const updated = prev.map((n) => ({
        ...n,
        read_at: n.read_at ?? new Date().toISOString(),
        read_by: n.read_by ?? "me",
      }));
      refreshUnreadCount(updated);
      return updated;
    });
  }

  const filtered =
    filter === "all"
      ? notifications
      : notifications.filter((n) => n.category === filter);

  const unreadCount = notifications.filter((n) => n.read_at === null).length;

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-40 bg-black/20"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Drawer */}
      <div className="fixed right-0 top-0 z-50 h-full w-96 bg-white shadow-2xl flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200">
          <div className="flex items-center gap-2">
            <h2 className="text-base font-semibold text-gray-900">
              Notifications
            </h2>
            {unreadCount > 0 && (
              <span className="bg-red-600 text-white text-xs font-bold px-1.5 py-0.5 rounded-full">
                {unreadCount}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            {unreadCount > 0 && (
              <button
                onClick={handleMarkAll}
                className="text-xs text-blue-600 hover:underline"
              >
                Mark all read
              </button>
            )}
            <button
              onClick={onClose}
              className="text-gray-400 hover:text-gray-600 text-lg leading-none"
            >
              ✕
            </button>
          </div>
        </div>

        {/* Filters */}
        <div className="flex gap-1 px-4 py-2 border-b border-gray-100">
          {(["all", "critical", "warning", "info"] as Filter[]).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`px-2 py-1 text-xs rounded capitalize transition-colors ${
                filter === f
                  ? "bg-gray-900 text-white"
                  : "text-gray-500 hover:bg-gray-100"
              }`}
            >
              {f}
            </button>
          ))}
        </div>

        {/* List */}
        <div className="flex-1 overflow-y-auto">
          {loading ? (
            <p className="text-center text-gray-400 text-sm py-8">Loading…</p>
          ) : filtered.length === 0 ? (
            <p className="text-center text-gray-400 text-sm py-8">
              No notifications
            </p>
          ) : (
            filtered.map((n) => (
              <div
                key={n.id}
                className={`px-4 py-3 border-b border-gray-100 flex gap-3 ${
                  n.read_at ? "opacity-60" : "bg-white"
                }`}
              >
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span
                      className={`text-xs font-medium px-1.5 py-0.5 rounded ${CATEGORY_STYLES[n.category] ?? "bg-gray-100 text-gray-700"}`}
                    >
                      {n.category}
                    </span>
                    <span className="text-xs text-gray-400 ml-auto shrink-0">
                      {relativeTime(n.created_at)}
                    </span>
                  </div>
                  <p className="text-sm font-medium text-gray-900 truncate">
                    {n.title}
                  </p>
                  <p className="text-xs text-gray-500 mt-0.5 line-clamp-2">
                    {n.body}
                  </p>
                  <p className="text-xs text-gray-400 mt-1">
                    source: {n.source}
                  </p>
                </div>
                {n.read_at === null && (
                  <button
                    onClick={() => handleMarkRead(n.id)}
                    className="shrink-0 text-xs text-blue-600 hover:underline self-start mt-1"
                  >
                    Mark read
                  </button>
                )}
              </div>
            ))
          )}
        </div>
      </div>
    </>
  );
}
