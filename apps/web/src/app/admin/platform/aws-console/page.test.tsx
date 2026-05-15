import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import AwsConsolePage from "./page";
import * as api from "@/lib/api";

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof api>();
  return {
    ...actual,
    getFederationUrl: vi.fn(),
  };
});

describe("AwsConsolePage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders all 5 AWS service cards", () => {
    render(<AwsConsolePage />);
    expect(screen.getByText("CloudWatch")).toBeTruthy();
    expect(screen.getByText("X-Ray")).toBeTruthy();
    expect(screen.getByText("AgentCore Observability")).toBeTruthy();
    expect(screen.getByText("Step Functions")).toBeTruthy();
    expect(screen.getByText("Bedrock")).toBeTruthy();
  });

  it("calls getFederationUrl with correct service on button click", async () => {
    const mockUrl = "https://signin.aws.amazon.com/federation?Action=login&...";
    vi.mocked(api.getFederationUrl).mockResolvedValue({
      url: mockUrl,
      expires_in: 900,
    });

    // Mock window.open
    const openSpy = vi.spyOn(window, "open").mockImplementation(() => null);

    render(<AwsConsolePage />);

    const buttons = screen.getAllByText("Abrir en AWS");
    fireEvent.click(buttons[0]!); // CloudWatch

    await waitFor(() => {
      expect(api.getFederationUrl).toHaveBeenCalledWith("cloudwatch", {
        dashboard: undefined,
        resourceId: undefined,
      });
      expect(openSpy).toHaveBeenCalledWith(mockUrl, "_blank", "noopener,noreferrer");
    });

    openSpy.mockRestore();
  });

  it("shows error message when getFederationUrl fails", async () => {
    vi.mocked(api.getFederationUrl).mockRejectedValue(
      new Error("AWS federation not configured in this environment."),
    );

    render(<AwsConsolePage />);
    const buttons = screen.getAllByText("Abrir en AWS");
    fireEvent.click(buttons[0]!);

    await waitFor(() => {
      expect(
        screen.getByText("AWS federation not configured in this environment."),
      ).toBeTruthy();
    });
  });
});
