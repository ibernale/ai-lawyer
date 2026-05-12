"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

const NAV = [
  { href: "/admin/governance", label: "Governance" },
  { href: "/admin/audit-trail", label: "Audit Trail" },
];

function getStoredRole(): string {
  if (typeof window === "undefined") return "";
  try {
    const token = sessionStorage.getItem("lex_agents_token");
    if (!token) return "";
    const payload = JSON.parse(atob(token.split(".")[1]));
    return payload.role ?? "";
  } catch {
    return "";
  }
}

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [role, setRole] = useState<string>("");
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const r = getStoredRole();
    setRole(r);
    setReady(true);
    if (r !== "operator" && r !== "admin") {
      router.replace("/");
    }
  }, [router]);

  if (!ready) return null;
  if (role !== "operator" && role !== "admin") {
    return (
      <div className="p-8 text-center text-red-600 font-semibold">
        Acceso denegado — se requiere rol operator o admin.
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <nav className="bg-white border-b border-gray-200 px-6 py-3 flex items-center gap-6">
        <span className="font-semibold text-gray-700 mr-4">Admin</span>
        {NAV.map(({ href, label }) => (
          <Link
            key={href}
            href={href}
            className={`text-sm font-medium px-3 py-1 rounded transition-colors ${
              pathname?.startsWith(href)
                ? "bg-blue-100 text-blue-700"
                : "text-gray-600 hover:text-gray-900"
            }`}
          >
            {label}
          </Link>
        ))}
        <span className="ml-auto text-xs text-gray-400">role: {role}</span>
      </nav>
      <main className="p-6">{children}</main>
    </div>
  );
}
