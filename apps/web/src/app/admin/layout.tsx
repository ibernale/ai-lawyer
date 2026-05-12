"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { getSystemState, setKillSwitch, type KillSwitchRow } from "@/lib/api";

const NAV = [
  { href: "/admin/ops", label: "Ops Center" },
  { href: "/admin/governance", label: "Governance" },
  { href: "/admin/audit-trail", label: "Audit Trail" },
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

  useEffect(() => {
    const r = getStoredRole();
    const u = getStoredUsername();
    setRole(r);
    setUsername(u);
    setReady(true);
    if (r !== "operator" && r !== "admin") {
      router.replace("/");
    }
    if (r === "operator" || r === "admin") {
      getSystemState()
        .then((state) => {
          const global = state.kill_switches.find(
            (k: KillSwitchRow) => k.target === "global",
          );
          setGlobalKillEngaged(global?.engaged ?? false);
        })
        .catch(() => {});
    }
  }, [router]);

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
  if (role !== "operator" && role !== "admin") {
    return (
      <div className="p-8 text-center text-red-600 font-semibold">
        Acceso denegado — se requiere rol operator o admin.
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
        <nav className="flex-1 px-2 py-4 space-y-1">
          {NAV.map(({ href, label }) => (
            <Link
              key={href}
              href={href as never}
              className={`block px-3 py-2 rounded text-sm font-medium transition-colors ${
                pathname?.startsWith(href)
                  ? "bg-gray-700 text-white"
                  : "text-gray-300 hover:bg-gray-800 hover:text-white"
              }`}
            >
              {label}
            </Link>
          ))}
          <div className="px-3 py-2 rounded text-sm text-gray-600 cursor-not-allowed">
            Costs &amp; FinOps
          </div>
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
          <div className="ml-auto">
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
    </div>
  );
}
