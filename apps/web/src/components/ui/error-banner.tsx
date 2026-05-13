"use client";

interface ErrorBannerProps {
  message: string;
  onRetry?: () => void;
  className?: string;
}

export function ErrorBanner({ message, onRetry, className }: ErrorBannerProps) {
  return (
    <div
      className={`rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800 flex items-start gap-3 ${className ?? ""}`}
      role="alert"
    >
      <svg
        className="w-4 h-4 shrink-0 mt-0.5 text-red-500"
        fill="none"
        stroke="currentColor"
        viewBox="0 0 24 24"
        aria-hidden="true"
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={2}
          d="M12 9v2m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"
        />
      </svg>
      <div className="flex-1 min-w-0">
        <span>{message}</span>
        {onRetry && (
          <button
            onClick={onRetry}
            className="ml-3 underline hover:no-underline font-medium whitespace-nowrap"
          >
            Reintentar
          </button>
        )}
      </div>
    </div>
  );
}
