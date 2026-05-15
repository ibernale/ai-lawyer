import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { Info, CheckCircle2, AlertTriangle, XCircle } from "lucide-react";
import { cn } from "@/lib/utils";

const alertVariants = cva(
  "relative flex w-full items-start gap-3 rounded-lg border px-4 py-3 text-sm",
  {
    variants: {
      variant: {
        info: "border-blue-200 bg-blue-50 text-blue-800",
        success: "border-green-200 bg-green-50 text-green-800",
        warning: "border-amber-200 bg-amber-50 text-amber-800",
        error: "border-red-200 bg-red-50 text-red-800",
      },
    },
    defaultVariants: { variant: "info" },
  },
);

const iconMap = {
  info: Info,
  success: CheckCircle2,
  warning: AlertTriangle,
  error: XCircle,
};

const iconColorMap = {
  info: "text-blue-500",
  success: "text-green-500",
  warning: "text-amber-500",
  error: "text-red-500",
};

export interface AlertProps
  extends
    React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof alertVariants> {
  title?: string;
}

const Alert = React.forwardRef<HTMLDivElement, AlertProps>(
  ({ className, variant = "info", title, children, ...props }, ref) => {
    const Icon = iconMap[variant ?? "info"];
    const iconColor = iconColorMap[variant ?? "info"];
    return (
      <div
        ref={ref}
        role={variant === "error" || variant === "warning" ? "alert" : "status"}
        className={cn(alertVariants({ variant }), className)}
        {...props}
      >
        <Icon
          className={cn("h-4 w-4 shrink-0 mt-0.5", iconColor)}
          aria-hidden="true"
        />
        <div className="flex-1 min-w-0">
          {title && <p className="font-semibold mb-0.5">{title}</p>}
          {children}
        </div>
      </div>
    );
  },
);
Alert.displayName = "Alert";

export { Alert, alertVariants };
