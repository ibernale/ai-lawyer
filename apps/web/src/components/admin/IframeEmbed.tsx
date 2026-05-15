"use client";

import { useState } from "react";

interface IframeEmbedProps {
  src: string;
  title: string;
  className?: string;
}

export function IframeEmbed({ src, title, className = "" }: IframeEmbedProps) {
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState(false);

  if (!src) {
    return (
      <div className="flex flex-col items-center justify-center h-full min-h-64 text-gray-500 gap-2">
        <svg className="w-10 h-10 text-gray-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
            d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
        </svg>
        <p className="text-sm">No configurado en este entorno</p>
        <p className="text-xs text-gray-400">Configura la URL del servicio en las variables de entorno</p>
      </div>
    );
  }

  return (
    <div className={`relative flex flex-col ${className}`}>
      {/* Toolbar */}
      <div className="flex items-center justify-between px-3 py-1.5 bg-gray-50 border border-gray-200 rounded-t text-xs text-gray-500">
        <span className="font-medium text-gray-700">{title}</span>
        <div className="flex items-center gap-3">
          {!loaded && !error && (
            <span className="flex items-center gap-1">
              <span className="w-2 h-2 rounded-full bg-yellow-400 animate-pulse" />
              Cargando...
            </span>
          )}
          {loaded && (
            <span className="flex items-center gap-1 text-green-600">
              <span className="w-2 h-2 rounded-full bg-green-500" />
              Activo
            </span>
          )}
          {error && (
            <span className="flex items-center gap-1 text-red-600">
              <span className="w-2 h-2 rounded-full bg-red-500" />
              Sin conexión
            </span>
          )}
          <a
            href={src}
            target="_blank"
            rel="noopener noreferrer"
            className="hover:text-gray-800 underline underline-offset-2"
          >
            Abrir en nueva pestaña ↗
          </a>
        </div>
      </div>

      {/* Loading skeleton */}
      {!loaded && !error && (
        <div className="absolute inset-0 top-8 bg-gray-100 animate-pulse rounded-b z-10" />
      )}

      <iframe
        src={src}
        title={title}
        className={`w-full flex-1 border border-t-0 border-gray-200 rounded-b ${error ? "hidden" : ""}`}
        style={{ minHeight: "calc(100vh - 200px)" }}
        sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-popups-to-escape-sandbox"
        onLoad={() => setLoaded(true)}
        onError={() => { setLoaded(true); setError(true); }}
      />

      {error && (
        <div className="flex flex-col items-center justify-center h-64 border border-t-0 border-gray-200 rounded-b bg-gray-50 text-gray-500 gap-2">
          <svg className="w-8 h-8 text-gray-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
              d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
          </svg>
          <p className="text-sm">No se pudo cargar {title}</p>
          <a href={src} target="_blank" rel="noopener noreferrer"
            className="text-xs text-blue-600 hover:underline">
            Intentar en nueva pestaña →
          </a>
        </div>
      )}
    </div>
  );
}
