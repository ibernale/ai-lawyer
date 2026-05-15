"use client";

import { Alert } from "@/components/ui/alert";

interface ErrorBannerProps {
  message: string;
  onRetry?: () => void;
  className?: string;
}

export function ErrorBanner({ message, onRetry, className }: ErrorBannerProps) {
  return (
    <Alert variant="error" className={className}>
      <span>{message}</span>
      {onRetry && (
        <button
          onClick={onRetry}
          className="ml-3 underline hover:no-underline font-medium whitespace-nowrap rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
        >
          Reintentar
        </button>
      )}
    </Alert>
  );
}
