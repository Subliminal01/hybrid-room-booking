"use client";

import { useEffect } from "react";

import { reportClientError } from "@/lib/api";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    void reportClientError({
      message: error.message || "React render error",
      source: "frontend-react",
      url: window.location.href,
      stack: error.stack ?? null,
      component_stack: error.digest ?? null,
      user_agent: navigator.userAgent,
    });
  }, [error]);

  return (
    <html lang="en">
      <body>
        <main className="error-page">
          <section className="panel">
            <div className="panel-header">
              <h1>Something went wrong</h1>
            </div>
            <div className="panel-body">
              <p className="muted">
                We have logged the issue. Please try again, or contact support if it keeps happening.
              </p>
              <button className="btn" type="button" onClick={reset}>
                Try again
              </button>
            </div>
          </section>
        </main>
      </body>
    </html>
  );
}
