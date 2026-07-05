#!/usr/bin/env node

const DEFAULT_FRONTEND_URL = "http://127.0.0.1:3000";
const DEFAULT_API_URL = "http://127.0.0.1:8000";

class SmokeTestError extends Error {}

function readArg(name, fallback) {
  const index = process.argv.indexOf(name);
  if (index === -1) {
    return fallback;
  }
  const value = process.argv[index + 1];
  if (!value || value.startsWith("--")) {
    throw new SmokeTestError(`${name} requires a value`);
  }
  return value;
}

function hasFlag(name) {
  return process.argv.includes(name);
}

function joinUrl(baseUrl, path) {
  return `${baseUrl.replace(/\/$/, "")}${path}`;
}

async function fetchRequired(url, label) {
  let response;
  try {
    response = await fetch(url, { redirect: "manual" });
  } catch (error) {
    throw new SmokeTestError(`Could not reach ${label} at ${url}: ${error.message}`);
  }

  if (!response.ok) {
    throw new SmokeTestError(`${label} returned ${response.status} for ${url}`);
  }
  return response;
}

async function fetchTextRequired(url, label) {
  const response = await fetchRequired(url, label);
  return {
    response,
    text: await response.text(),
  };
}

function assertIncludes(text, fragment, label) {
  if (!text.includes(fragment)) {
    throw new SmokeTestError(`${label} is missing ${JSON.stringify(fragment)}`);
  }
}

function assertFragments(text, fragments, label) {
  for (const fragment of fragments) {
    assertIncludes(text, fragment, label);
  }
}

function assertHeader(response, headerName, expectedValue) {
  const actualValue = response.headers.get(headerName);
  if (actualValue !== expectedValue) {
    throw new SmokeTestError(
      `Expected ${headerName}: ${expectedValue}, received ${actualValue ?? "<missing>"}`,
    );
  }
}

async function run() {
  const frontendUrl = readArg(
    "--frontend-url",
    process.env.FRONTEND_URL ?? DEFAULT_FRONTEND_URL,
  );
  const apiUrl = readArg("--api-url", process.env.API_URL ?? DEFAULT_API_URL);
  const skipBackend = hasFlag("--skip-backend") || process.env.SKIP_BACKEND_SMOKE === "true";

  console.log(`1. Checking frontend at ${frontendUrl}`);
  const { response: frontendResponse, text: html } = await fetchTextRequired(frontendUrl, "frontend");
  assertHeader(frontendResponse, "x-content-type-options", "nosniff");
  assertHeader(frontendResponse, "x-frame-options", "DENY");
  assertHeader(frontendResponse, "referrer-policy", "no-referrer");
  assertHeader(
    frontendResponse,
    "permissions-policy",
    "camera=(), microphone=(), geolocation=()",
  );

  assertFragments(html, [
    "Hybrid Stay Booking",
    "Affordable workday rooms",
    "Search Rota",
    "Login",
    "/privacy",
    "/terms",
    "/refunds",
    "/contact",
    "/_next/static/",
  ], "Frontend HTML");

  const publicPages = [
    ["/privacy", "Privacy Policy"],
    ["/terms", "Terms of Service"],
    ["/refunds", "Cancellation and Refund Policy"],
    ["/contact", "Contact and Support"],
  ];
  for (const [path, heading] of publicPages) {
    console.log(`2. Checking public page ${path}`);
    const { text } = await fetchTextRequired(joinUrl(frontendUrl, path), `frontend ${path}`);
    assertFragments(text, [heading, "Back to booking"], `Frontend ${path}`);
  }

  if (skipBackend) {
    console.log("3. Skipping backend readiness check");
  } else {
    console.log(`3. Checking backend readiness at ${apiUrl}`);
    const readyResponse = await fetchRequired(joinUrl(apiUrl, "/health/ready"), "backend");
    const ready = await readyResponse.json();
    if (ready.status !== "ready" || ready.database !== "ok") {
      throw new SmokeTestError(`Unexpected backend readiness payload: ${JSON.stringify(ready)}`);
    }
  }

  console.log("Frontend smoke test passed");
}

run().catch((error) => {
  if (error instanceof SmokeTestError) {
    console.error(error.message);
  } else {
    console.error(error);
  }
  process.exit(1);
});
