"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  getSystemState,
  setKillSwitch,
  getNotificationsCount,
  listAuditSamples,
  type KillSwitchRow,
} from "@/lib/api";
import { NotificationsDrawer } from "@/components/admin/NotificationsDrawer";
import { Logo } from "@/components/Logo";
import { Button } from "@/components/ui/button";

type NavItem = {
  href: string;
  label: string;
  placeholder?: boolean;
  badge?: number;
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
      { href: "/admin/review-queue", label: "Cola de revisión" },
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
  const dialogRef = useRef<HTMLDivElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    previousFocusRef.current = document.activeElement as HTMLElement;
    return () => {
      previousFocusRef.current?.focus();
    };
  }, []);

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        onCancel();
        return;
      }
      if (e.key !== "Tab") return;
      const dialog = dialogRef.current;
      if (!dialog) return;
      const focusable = dialog.querySelectorAll<HTMLElement>(
        'button:not([disabled]), textarea, [tabindex]:not([tabindex="-1"])',
      );
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (e.shiftKey) {
        if (document.activeElement === first) {
          e.preventDefault();
          last?.focus();
        }
      } else {
        if (document.activeElement === last) {
          e.preventDefault();
          first?.focus();
        }
      }
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [onCancel]);

  return (
    <div
      className="fixed inset-0 bg-black/50 flex items-center justify-center z-50"
      aria-hidden="true"
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="kill-dialog-title"
        className="bg-white rounded-lg shadow-xl p-6 w-full max-w-md"
        aria-hidden="false"
      >
        <h2 id="kill-dialog-title" className="text-lg font-semibold mb-4">
          {title}
        </h2>
        <label
          htmlFor="kill-reason"
          className="block text-sm font-medium text-gray-700 mb-1"
        >
          Motivo <span aria-hidden="true">*</span>
          <span className="sr-only">(obligatorio)</span>
        </label>
        <textarea
          id="kill-reason"
          className="w-full border border-gray-300 rounded p-2 text-sm resize-none h-24 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
          placeholder="Describe el motivo..."
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          autoFocus
        />
        <div className="flex gap-3 justify-end mt-4">
          <button
            onClick={onCancel}
            className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900 border border-gray-300 rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
          >
            Cancelar
          </button>
          <button
            onClick={() => onConfirm(reason)}
            disabled={!reason.trim()}
            className="px-4 py-2 text-sm font-medium bg-red-600 text-white rounded hover:bg-red-700 disabled:opacity-40 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
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
  const [pendingReviewCount, setPendingReviewCount] = useState(0);

  useEffect(() => {
    const r = getStoredRole();
    const u = getStoredUsername();
    setRole(r);
    setUsername(u);
    setReady(true);
    if (r !== "viewer" && r !== "operator" && r !== "admin") {
      router.replace("/admin-login");
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
      listAuditSamples("pending", 100)
        .then((samples) => setPendingReviewCount(samples.length))
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

  // Inject live badge counts into the static nav definition.
  const navSections = useMemo(
    () =>
      NAV_SECTIONS.map((section) => ({
        ...section,
        items: section.items.map((item) =>
          item.href === "/admin/review-queue" && pendingReviewCount > 0
            ? { ...item, badge: pendingReviewCount }
            : item,
        ),
      })),
    [pendingReviewCount],
  );

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

  const bellLabel =
    unreadCount > 0
      ? `Notificaciones, ${unreadCount} sin leer`
      : "Notificaciones";

  return (
    <div className="min-h-screen bg-gray-50 flex">
      {/* Sidebar */}
      <aside className="w-56 bg-[#1a1a1a] text-white flex flex-col shrink-0">
        <div className="px-4 py-4 border-b border-white/10">
          <Logo variant="full" className="mb-3" />
          <span
            role="status"
            className={`inline-flex items-center gap-1.5 text-xs font-medium px-2 py-0.5 rounded-full ${
              globalKillEngaged
                ? "bg-red-700 text-white"
                : "bg-green-700 text-white"
            }`}
          >
            <span
              className={`w-1.5 h-1.5 rounded-full ${globalKillEngaged ? "bg-red-300" : "bg-green-400"}`}
              aria-hidden="true"
            />
            {globalKillEngaged ? "KILL ACTIVE" : "OK"}
          </span>
        </div>
        <nav
          aria-label="Secciones de administración"
          className="flex-1 px-2 py-3 overflow-y-auto"
        >
          {navSections.map((section) => (
            <div key={section.label} className="mb-4">
              <h2 className="px-3 mb-1 text-[10px] font-semibold uppercase tracking-widest text-gray-400">
                {section.label}
              </h2>
              <div className="space-y-0.5">
                {section.items.map(({ href, label, placeholder, badge }) =>
                  placeholder ? (
                    <div
                      key={href}
                      aria-disabled="true"
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
                      aria-current={
                        pathname?.startsWith(href) ? "page" : undefined
                      }
                      className={`flex items-center justify-between px-3 py-1.5 rounded text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 ${
                        pathname?.startsWith(href)
                          ? "bg-primary text-white"
                          : "text-gray-300 hover:bg-white/10 hover:text-white"
                      }`}
                    >
                      <span>{label}</span>
                      {badge !== undefined && badge > 0 && (
                        <span className="ml-1.5 text-[10px] font-bold bg-yellow-500 text-white px-1.5 py-0.5 rounded-full leading-none">
                          {badge > 99 ? "99+" : badge}
                        </span>
                      )}
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
              <span className="sr-only">Rol: </span>
              {role}
            </span>
          </span>
          <div className="ml-auto flex items-center gap-3">
            {/* Bell icon */}
            <button
              onClick={() => setShowNotifications(true)}
              className="relative p-2 text-gray-500 hover:text-gray-700 rounded-full hover:bg-gray-100 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
              aria-label={bellLabel}
            >
              <svg
                className="w-5 h-5"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
                aria-hidden="true"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9"
                />
              </svg>
              {unreadCount > 0 && (
                <span
                  aria-hidden="true"
                  className="absolute -top-0.5 -right-0.5 bg-red-600 text-white text-xs font-bold w-4 h-4 rounded-full flex items-center justify-center leading-none"
                >
                  {unreadCount > 9 ? "9+" : unreadCount}
                </span>
              )}
            </button>

            {/* Kill switch */}
            {role === "admin" && (
              <Button
                onClick={() => setShowKillDialog(true)}
                loading={killBusy}
                variant={globalKillEngaged ? "secondary" : "destructive"}
                size="md"
                className={
                  globalKillEngaged
                    ? "bg-green-600 hover:bg-green-700 text-white"
                    : undefined
                }
              >
                {globalKillEngaged
                  ? "Release Kill Switch"
                  : "Global Kill Switch"}
              </Button>
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
