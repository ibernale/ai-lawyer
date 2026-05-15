import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { IframeEmbed } from "./IframeEmbed";

// IframeEmbed is a pure presentational component — no API calls.

describe("IframeEmbed", () => {
  it("renders placeholder when src is empty", () => {
    render(<IframeEmbed src="" title="Grafana" />);
    expect(screen.getByText("No configurado en este entorno")).toBeTruthy();
  });

  it("renders iframe with correct src when provided", () => {
    render(<IframeEmbed src="http://localhost:3001" title="Grafana" />);
    const iframe = document.querySelector("iframe");
    expect(iframe).toBeTruthy();
    expect(iframe?.getAttribute("src")).toBe("http://localhost:3001");
  });

  it("renders open-in-new-tab link when src is provided", () => {
    render(<IframeEmbed src="http://localhost:3001" title="Grafana" />);
    const link = screen.getByText("Abrir en nueva pestaña ↗");
    expect(link.getAttribute("href")).toBe("http://localhost:3001");
    expect(link.getAttribute("target")).toBe("_blank");
  });

  it("applies sandbox attribute to iframe", () => {
    render(<IframeEmbed src="http://localhost:3001" title="Test" />);
    const iframe = document.querySelector("iframe");
    expect(iframe?.getAttribute("sandbox")).toContain("allow-scripts");
    expect(iframe?.getAttribute("sandbox")).toContain("allow-same-origin");
  });

  it("shows title in toolbar", () => {
    render(<IframeEmbed src="http://localhost:3001" title="Grafana Dashboard" />);
    expect(screen.getByText("Grafana Dashboard")).toBeTruthy();
  });
});
