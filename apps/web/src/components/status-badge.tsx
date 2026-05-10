import { Badge } from "@/components/ui/badge";

type Status = "healthy" | "degraded" | "unavailable" | "unknown";

const STATUS_CONFIG: Record<
  Status,
  { label: string; variant: "success" | "warning" | "error" | "outline" }
> = {
  healthy: { label: "Healthy", variant: "success" },
  degraded: { label: "Degraded", variant: "warning" },
  unavailable: { label: "Unavailable", variant: "error" },
  unknown: { label: "Unknown", variant: "outline" },
};

interface StatusBadgeProps {
  status: Status;
  label?: string;
}

export function StatusBadge({ status, label }: StatusBadgeProps) {
  const config = STATUS_CONFIG[status] ?? STATUS_CONFIG["unknown"];
  return (
    <Badge variant={config.variant}>
      <span className="mr-1" aria-hidden>
        {status === "healthy" ? "●" : status === "degraded" ? "◐" : "○"}
      </span>
      {label ?? config.label}
    </Badge>
  );
}
