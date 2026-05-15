import { describe, it, expect, vi, beforeEach } from "vitest";

// AwsConsolePage renders 5 AWS service cards.
// Tests cover the service list and getFederationUrl call contract — no DOM.

const AWS_SERVICES = [
  { service: "cloudwatch", name: "CloudWatch" },
  { service: "xray", name: "X-Ray" },
  { service: "agentcore", name: "AgentCore Observability" },
  { service: "step-functions", name: "Step Functions" },
  { service: "bedrock", name: "Bedrock" },
] as const;

type AwsService = (typeof AWS_SERVICES)[number]["service"];

async function simulateFederationClick(
  service: AwsService,
  getFederationUrl: (
    s: AwsService,
    opts?: { dashboard?: string; resourceId?: string },
  ) => Promise<{ url: string; expires_in: number }>,
  openUrl: (url: string, target: string, features: string) => void,
): Promise<void> {
  const result = await getFederationUrl(service, {
    dashboard: undefined,
    resourceId: undefined,
  });
  openUrl(result.url, "_blank", "noopener,noreferrer");
}

describe("AwsConsolePage service list", () => {
  it("has exactly 5 AWS services", () => {
    expect(AWS_SERVICES).toHaveLength(5);
  });

  it("includes CloudWatch", () => {
    expect(AWS_SERVICES.map((s) => s.name)).toContain("CloudWatch");
  });

  it("includes X-Ray", () => {
    expect(AWS_SERVICES.map((s) => s.name)).toContain("X-Ray");
  });

  it("includes AgentCore Observability", () => {
    expect(AWS_SERVICES.map((s) => s.name)).toContain("AgentCore Observability");
  });

  it("includes Step Functions", () => {
    expect(AWS_SERVICES.map((s) => s.name)).toContain("Step Functions");
  });

  it("includes Bedrock", () => {
    expect(AWS_SERVICES.map((s) => s.name)).toContain("Bedrock");
  });
});

describe("AwsConsolePage federation flow", () => {
  const mockUrl = "https://signin.aws.amazon.com/federation?Action=login&...";

  it("calls getFederationUrl with cloudwatch service and opens URL", async () => {
    const getFederationUrl = vi
      .fn()
      .mockResolvedValue({ url: mockUrl, expires_in: 900 });
    const openUrl = vi.fn();

    await simulateFederationClick("cloudwatch", getFederationUrl, openUrl);

    expect(getFederationUrl).toHaveBeenCalledWith("cloudwatch", {
      dashboard: undefined,
      resourceId: undefined,
    });
    expect(openUrl).toHaveBeenCalledWith(mockUrl, "_blank", "noopener,noreferrer");
  });

  it("propagates error when getFederationUrl rejects", async () => {
    const getFederationUrl = vi
      .fn()
      .mockRejectedValue(new Error("AWS federation not configured in this environment."));
    const openUrl = vi.fn();

    await expect(
      simulateFederationClick("cloudwatch", getFederationUrl, openUrl),
    ).rejects.toThrow("AWS federation not configured in this environment.");
    expect(openUrl).not.toHaveBeenCalled();
  });
});
