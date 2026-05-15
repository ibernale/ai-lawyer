import * as React from "react";
import Image from "next/image";
import { cn } from "@/lib/utils";

interface LogoProps {
  variant?: "full" | "icon";
  className?: string;
}

const LOGO_URL = process.env.NEXT_PUBLIC_LOGO_URL;

export function Logo({ variant = "full", className }: LogoProps) {
  if (LOGO_URL) {
    return (
      <Image
        src={LOGO_URL}
        alt="Lex Agents"
        width={variant === "icon" ? 32 : 120}
        height={32}
        className={cn("object-contain", className)}
      />
    );
  }

  if (variant === "icon") {
    return (
      <span
        role="img"
        aria-label="Lex Agents"
        className={cn(
          "inline-flex h-8 w-8 items-center justify-center rounded bg-primary text-primary-foreground text-xs font-bold",
          className,
        )}
      >
        LA
      </span>
    );
  }

  return (
    <span
      role="img"
      aria-label="Lex Agents"
      className={cn("inline-flex items-center gap-2", className)}
    >
      <span className="inline-flex h-7 w-7 items-center justify-center rounded bg-primary text-primary-foreground text-xs font-bold">
        LA
      </span>
      <span className="text-sm font-semibold text-white">Lex Agents</span>
    </span>
  );
}
