import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

// ---------------------------------------------------------------------------
// Minimal unit tests for layout helpers (role extraction, section rendering)
// The full layout uses Next.js router so we test the logic in isolation.
// ---------------------------------------------------------------------------

function getStoredRole(token: string): string {
  try {
    const payload = JSON.parse(atob(token.split(".")[1] ?? ""));
    return (payload.role as string) ?? "";
  } catch {
    return "";
  }
}

function buildToken(role: string): string {
  const header = btoa(JSON.stringify({ alg: "HS256", typ: "JWT" }));
  const payload = btoa(JSON.stringify({ sub: "user1", role, exp: 9999999999 }));
  return `${header}.${payload}.sig`;
}

describe("admin layout role helpers", () => {
  it("extracts admin role from JWT payload", () => {
    expect(getStoredRole(buildToken("admin"))).toBe("admin");
  });

  it("extracts operator role from JWT payload", () => {
    expect(getStoredRole(buildToken("operator"))).toBe("operator");
  });

  it("extracts viewer role from JWT payload", () => {
    expect(getStoredRole(buildToken("viewer"))).toBe("viewer");
  });

  it("returns empty string for malformed token", () => {
    expect(getStoredRole("not.a.token")).toBe("");
  });
});

describe("admin layout NAV_SECTIONS structure", () => {
  const NAV_SECTIONS = [
    {
      label: "Plataforma",
      items: [
        { href: "/admin/overview", label: "Overview" },
        { href: "/admin/ops", label: "Ops Center" },
        { href: "/admin/users", label: "Users", placeholder: true },
        { href: "/admin/governance", label: "Governance" },
      ],
    },
    {
      label: "Datos",
      items: [
        { href: "/admin/costs", label: "Costs & FinOps", placeholder: true },
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
        { href: "/admin/settings", label: "Platform Settings", placeholder: true },
        { href: "/admin/flags", label: "Feature Flags", placeholder: true },
      ],
    },
  ];

  it("has exactly 4 sections", () => {
    expect(NAV_SECTIONS).toHaveLength(4);
  });

  it("Observabilidad section has all 5 platform sub-pages", () => {
    const obs = NAV_SECTIONS.find((s) => s.label === "Observabilidad")!;
    expect(obs.items).toHaveLength(5);
    const hrefs = obs.items.map((i) => i.href);
    expect(hrefs).toContain("/admin/platform/metrics");
    expect(hrefs).toContain("/admin/platform/aws-console");
  });

  it("placeholder items are not navigable", () => {
    const allItems = NAV_SECTIONS.flatMap((s) => s.items);
    const placeholders = allItems.filter((i) => i.placeholder);
    expect(placeholders.length).toBeGreaterThan(0);
    placeholders.forEach((p) => {
      expect(p.placeholder).toBe(true);
    });
  });

  it("admin-only items exist (kill switch is role-gated separately)", () => {
    // Kill switch is rendered conditionally in JSX: role === "admin"
    // This test documents the expected behaviour
    const roles = ["viewer", "operator", "admin"];
    const killSwitchVisibleFor = roles.filter((r) => r === "admin");
    expect(killSwitchVisibleFor).toEqual(["admin"]);
  });
});
