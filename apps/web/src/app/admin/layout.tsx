"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  getSystemState,
  setKillSwitch,
  getNotificationsCount,
  type KillSwitchRow,
} from "@/lib/api";
import { NotificationsDrawer } from "@/components/admin/NotificationsDrawer";

type NavItem = {
  href: string;
  label: string;
  placeholder?: boolean;
};

type NavSection = {
  label: string;
  items: NavItem[];
};

const NAV_SECTIONS: NavSection[] = [
  {
    label: "Plataforma",
    items: [
      { href: "/admin/overview", label: "Overview" },
      { href: "/admin/ops", label: "Ops Center" },
      { href: "/admin/users", label: "Users" },
      { href: "/admin/governance", label: "Governance" },
    ],
  },
  {
    label: "Datos",
    items: [
      { href: "/admin/costs", label: "Costs & FinOps" },
      { href: "/admin/audit-trail", label: "Audit Trail" },
    ],
  },
  {
    label: "Observabilidad",
    items: [
      { href: "/admin/platform/metrics", label: "Metrics" },
      { href: "/admin/platform/traces-llm", label: "Traces LLM" },
      { href: "/admin/platform/traces-infra", label: "Traces Infra" },
      { href: "/admin/platform/pipelines", label: "Pipelines" },
      { href: "/admin/platform/aws-console", label: "AWS Console" },
    ],
  },
  {
    label: "Settings",
    items: [
      { href: "/admin/settings", label: "Platform Settings" },
      { href: "/admin/flags", label: "Feature Flags" },
    ],
  },
];

function getStoredRole(): string {
  if (typeof window === "undefined") return "";
  try {
    const token = sessionStorage.getItem("lex_agents_token");
    if (!token) return "";
    const payload = JSON.parse(atob(token.split(".")[1] ?? ""));
    return (payload.role as string) ?? "";
  } catch {
    return "";
  }
}

function getStoredUsername(): string {
  if (typeof window === "undefined") return "";
  try {
    const token = sessionStorage.getItem("lex_agents_token");
    if (!token) return "";
    const payload = JSON.parse(atob(token.split(".")[1] ?? ""));
    return (payload.sub as string) ?? "";
  } catch {
    return "";
  }
}

function ReasonDialog({
  title,
  onConfirm,
  onCancel,
}: {
  title: string;
  onConfirm: (reason: string) => void;
  onCancel: () => void;
}) {
  const [reason, setReason] = useState("");
  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg shadow-xl p-6 w-full max-w-md">
        <h2 className="text-lg font-semibold mb-4">{title}</h2>
        <textarea
          className="w-full border border-gray-300 rounded p-2 text-sm resize-none h-24 focus:outline-none focus:ring-2 focus:ring-blue-500"
          placeholder="Motivo obligatorio..."
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          autoFocus
        />
        <div className="flex gap-3 justify-end mt-4">
          <button
            onClick={onCancel}
            className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900 border border-gray-300 rounded"
          >
            Cancelar
          </button>
          <button
            onClick={() => onConfirm(reason)}
            disabled={!reason.trim()}
            className="px-4 py-2 text-sm font-medium bg-red-600 text-white rounded hover:bg-red-700 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            Confirmar
          </button>
        </div>
      </div>
    </div>
  );
}

export default function AdminLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const [role, setRole] = useState<string>("");
  const [username, setUsername] = useState<string>("");
  const [ready, setReady] = useState(false);
  const [globalKillEngaged, setGlobalKillEngaged] = useState(false);
  const [showKillDialog, setShowKillDialog] = useState(false);
  const [killBusy, setKillBusy] = useState(false);
  const [unreadCount, setUnreadCount] = useState(0);
  const [showNotifications, setShowNotifications] = useState(false);

  useEffect(() => {
    const r = getStoredRole();
    const u = getStoredUsername();
    setRole(r);
    setUsername(u);
    setReady(true);
    if (r !== "viewer" && r !== "operator" && r !== "admin") {
      router.replace("/");
    }
    if (r === "viewer" || r === "operator" || r === "admin") {
      getSystemState()
        .then((state) => {
          const global = state.kill_switches.find(
            (k: KillSwitchRow) => k.target === "global",
          );
          setGlobalKillEngaged(global?.engaged ?? false);
        })
        .catch(() => {});
      getNotificationsCount()
        .then((data) => setUnreadCount(data.unread))
        .catch(() => {});
    }
  }, [router]);

  // Poll unread count every 30s
  useEffect(() => {
    if (!role || (role !== "operator" && role !== "admin")) return;
    const interval = setInterval(() => {
      getNotificationsCount()
        .then((data) => setUnreadCount(data.unread))
        .catch(() => {});
    }, 30_000);
    return () => clearInterval(interval);
  }, [role]);

  async function handleKillSwitch(reason: string) {
    setShowKillDialog(false);
    setKillBusy(true);
    try {
      await setKillSwitch("global", !globalKillEngaged, reason);
      setGlobalKillEngaged((prev) => !prev);
    } catch {
      /* ignore */
    } finally {
      setKillBusy(false);
    }
  }

  if (!ready) return null;
  if (role !== "viewer" && role !== "operator" && role !== "admin") {
    return (
      <div className="p-8 text-center text-red-600 font-semibold">
        Acceso denegado — se requiere rol viewer, operator o admin.
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50 flex">
      {/* Sidebar */}
      <aside className="w-56 bg-gray-900 text-white flex flex-col shrink-0">
        <div className="px-4 py-4 border-b border-gray-700">
          <div className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1">
            Sistema
          </div>
          <span
            className={`inline-flex items-center gap-1.5 text-xs font-medium px-2 py-0.5 rounded-full ${
              globalKillEngaged
                ? "bg-red-700 text-red-100"
                : "bg-green-800 text-green-200"
            }`}
          >
            <span
              className={`w-1.5 h-1.5 rounded-full ${globalKillEngaged ? "bg-red-300" : "bg-green-400"}`}
            />
            {globalKillEngaged ? "KILL ACTIVE" : "OK"}
          </span>
        </div>
        <nav className="flex-1 px-2 py-3 overflow-y-auto">
          {NAV_SECTIONS.map((section) => (
            <div key={section.label} className="mb-4">
              <div className="px-3 mb-1 text-[10px] font-semibold uppercase tracking-widest text-gray-500">
                {section.label}
              </div>
              <div className="space-y-0.5">
                {section.items.map(({ href, label, placeholder }) =>
                  placeholder ? (
                    <div
                      key={href}
                      className="flex items-center justify-between px-3 py-1.5 rounded text-sm text-gray-600 cursor-not-allowed select-none"
                    >
                      <span>{label}</span>
                      <span className="text-[9px] font-medium uppercase tracking-wide bg-gray-800 text-gray-500 px-1.5 py-0.5 rounded">
                        Pronto
                      </span>
                    </div>
                  ) : (
                    <Link
                      key={href}
                      href={href as never}
                      className={`block px-3 py-1.5 rounded text-sm font-medium transition-colors ${
                        pathname?.startsWith(href)
                          ? "bg-gray-700 text-white"
                          : "text-gray-300 hover:bg-gray-800 hover:text-white"
                      }`}
                    >
                      {label}
                    </Link>
                  ),
                )}
              </div>
            </div>
          ))}
        </nav>
      </aside>

      {/* Main area */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Top bar */}
        <header className="bg-white border-b border-gray-200 px-6 py-3 flex items-center gap-4 shrink-0">
          <span className="text-sm text-gray-600">
            {username}{" "}
            <span className="bg-blue-100 text-blue-700 text-xs font-medium px-1.5 py-0.5 rounded">
              {role}
            </span>
          </span>
          <div className="ml-auto flex items-center gap-3">
            {/* Bell icon */}
            <button
              onClick={() => setShowNotifications(true)}
              className="relative p-2 text-gray-500 hover:text-gray-700 rounded-full hover:bg-gray-100 transition-colors"
              aria-label="Notifications"
            >
              <svg
                className="w-5 h-5"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9"
                />
              </svg>
              {unreadCount > 0 && (
                <span className="absolute -top-0.5 -right-0.5 bg-red-600 text-white text-xs font-bold w-4 h-4 rounded-full flex items-center justify-center leading-none">
                  {unreadCount > 9 ? "9+" : unreadCount}
                </span>
              )}
            </button>

            {/* Kill switch */}
            {role === "admin" && (
              <button
                onClick={() => setShowKillDialog(true)}
                disabled={killBusy}
                className={`px-4 py-2 text-sm font-semibold rounded transition-colors disabled:opacity-50 ${
                  globalKillEngaged
                    ? "bg-green-600 hover:bg-green-700 text-white"
                    : "bg-red-600 hover:bg-red-700 text-white"
                }`}
              >
                {globalKillEngaged
                  ? "Release Kill Switch"
                  : "Global Kill Switch"}
              </button>
            )}
          </div>
        </header>

        <main className="flex-1 p-6 overflow-auto">{children}</main>
      </div>

      {showKillDialog && (
        <ReasonDialog
          title={
            globalKillEngaged
              ? "Release Global Kill Switch"
              : "Engage Global Kill Switch"
          }
          onConfirm={handleKillSwitch}
          onCancel={() => setShowKillDialog(false)}
        />
      )}

      {showNotifications && (
        <NotificationsDrawer
          onClose={() => setShowNotifications(false)}
          onCountChange={setUnreadCount}
        />
      )}
    </div>
  );
}
