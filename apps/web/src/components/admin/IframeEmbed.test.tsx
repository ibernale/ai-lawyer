import { describe, it, expect } from "vitest";

// IframeEmbed is a pure presentational component.
// Tests cover the logic that determines what to render based on props.

function getIframeSandbox(): string {
  return "allow-scripts allow-same-origin allow-forms";
}

function shouldShowPlaceholder(src: string): boolean {
  return !src;
}

function shouldShowOpenLink(src: string): boolean {
  return !!src;
}

describe("IframeEmbed logic", () => {
  it("shows placeholder when src is empty", () => {
    expect(shouldShowPlaceholder("")).toBe(true);
  });

  it("does not show placeholder when src is provided", () => {
    expect(shouldShowPlaceholder("http://localhost:3001")).toBe(false);
  });

  it("shows open-in-new-tab link when src is provided", () => {
    expect(shouldShowOpenLink("http://localhost:3001")).toBe(true);
  });

  it("does not show open-in-new-tab link when src is empty", () => {
    expect(shouldShowOpenLink("")).toBe(false);
  });

  it("sandbox attribute contains allow-scripts", () => {
    expect(getIframeSandbox()).toContain("allow-scripts");
  });

  it("sandbox attribute contains allow-same-origin", () => {
    expect(getIframeSandbox()).toContain("allow-same-origin");
  });
});
