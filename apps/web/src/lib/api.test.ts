import { describe, it, expect } from "vitest";
import type { ConsultResponse } from "./api";

// ---------------------------------------------------------------------------
// Type-level helpers used by components
// ---------------------------------------------------------------------------

function hasBranchAnswers(response: ConsultResponse): boolean {
  return !!(response.branch_answers && Object.keys(response.branch_answers).length > 1);
}

function branchNames(response: ConsultResponse): string[] {
  return response.planner_output?.branches.map((b) => b.name) ?? [];
}

function totalCost(response: ConsultResponse): number {
  return Object.values(response.cost_breakdown_by_agent ?? {}).reduce((a, b) => a + b, 0);
}

// ---------------------------------------------------------------------------
// Minimal ConsultResponse factory
// ---------------------------------------------------------------------------

function makeResponse(overrides: Partial<ConsultResponse> = {}): ConsultResponse {
  return {
    trace_id: "test-trace",
    answer: "test answer",
    citations: [],
    verification: null,
    query_rewritten: "test query",
    routing: { branch: "regulatorio_bancario" },
    metadata: {},
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("hasBranchAnswers", () => {
  it("returns false when branch_answers is absent", () => {
    expect(hasBranchAnswers(makeResponse())).toBe(false);
  });

  it("returns false when branch_answers has only one entry", () => {
    expect(
      hasBranchAnswers(makeResponse({ branch_answers: { regulatorio_bancario: "answer" } })),
    ).toBe(false);
  });

  it("returns true when branch_answers has multiple entries", () => {
    expect(
      hasBranchAnswers(
        makeResponse({
          branch_answers: {
            regulatorio_bancario: "answer 1",
            datos_personales_rgpd: "answer 2",
          },
        }),
      ),
    ).toBe(true);
  });
});

describe("branchNames", () => {
  it("returns empty array when planner_output is absent", () => {
    expect(branchNames(makeResponse())).toEqual([]);
  });

  it("returns branch names from planner_output", () => {
    const response = makeResponse({
      planner_output: {
        branches: [
          { name: "regulatorio_bancario", priority: 1, weight: 0.6 },
          { name: "datos_personales_rgpd", priority: 2, weight: 0.4 },
        ],
        jurisdictions: ["ES", "EU"],
        output_type: "dictamen",
        depth: "deep",
        sub_tasks: [],
      },
    });
    expect(branchNames(response)).toEqual(["regulatorio_bancario", "datos_personales_rgpd"]);
  });
});

describe("totalCost", () => {
  it("returns 0 when no cost breakdown", () => {
    expect(totalCost(makeResponse())).toBe(0);
  });

  it("returns sum of all branch costs", () => {
    const response = makeResponse({
      cost_breakdown_by_agent: {
        regulatorio_bancario: 0.12,
        datos_personales_rgpd: 0.08,
      },
    });
    expect(totalCost(response)).toBeCloseTo(0.2);
  });
});

describe("ConsultResponse shape", () => {
  it("branch_answers defaults to undefined (absent field)", () => {
    const r = makeResponse();
    expect(r.branch_answers).toBeUndefined();
  });

  it("jurisdictions multi-select populated correctly", () => {
    const r = makeResponse({
      routing: {
        branch: "regulatorio_bancario",
        jurisdictions: ["ES", "EU", "UK", "BR"],
      },
    });
    expect(r.routing.jurisdictions).toHaveLength(4);
    expect(r.routing.jurisdictions).toContain("ES");
    expect(r.routing.jurisdictions).toContain("BR");
  });
});
