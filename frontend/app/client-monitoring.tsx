"use client";

import { useEffect } from "react";

import { reportClientError } from "@/lib/api";

function messageFromReason(reason: unknown) {
  if (reason instanceof Error) {
    return reason.message;
  }
  if (typeof reason === "string") {
    return reason;
  }
  return "Unhandled browser promise rejection";
}

function stackFromReason(reason: unknown) {
  return reason instanceof Error ? reason.stack ?? null : null;
}

export function ClientMonitoring() {
  useEffect(() => {
    function reportWindowError(event: ErrorEvent) {
      void reportClientError({
        message: event.message || "Unhandled browser error",
        url: window.location.href,
        stack: event.error instanceof Error ? event.error.stack ?? null : null,
        user_agent: navigator.userAgent,
      });
    }

    function reportUnhandledRejection(event: PromiseRejectionEvent) {
      void reportClientError({
        message: messageFromReason(event.reason),
        url: window.location.href,
        stack: stackFromReason(event.reason),
        user_agent: navigator.userAgent,
      });
    }

    window.addEventListener("error", reportWindowError);
    window.addEventListener("unhandledrejection", reportUnhandledRejection);
    return () => {
      window.removeEventListener("error", reportWindowError);
      window.removeEventListener("unhandledrejection", reportUnhandledRejection);
    };
  }, []);

  return null;
}
