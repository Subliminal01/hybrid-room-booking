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

  console.log(`1. Checking frontend at ${frontendUrl}`);
  const frontendResponse = await fetchRequired(frontendUrl, "frontend");
  assertHeader(frontendResponse, "x-content-type-options", "nosniff");
  assertHeader(frontendResponse, "x-frame-options", "DENY");
  assertHeader(frontendResponse, "referrer-policy", "no-referrer");
  assertHeader(
    frontendResponse,
    "permissions-policy",
    "camera=(), microphone=(), geolocation=()",
  );

  const html = await frontendResponse.text();
  const requiredFragments = [
    "Hybrid Stay Booking",
    "Affordable workday rooms",
    "/_next/static/",
  ];
  for (const fragment of requiredFragments) {
    if (!html.includes(fragment)) {
      throw new SmokeTestError(`Frontend HTML is missing ${JSON.stringify(fragment)}`);
    }
  }

  console.log(`2. Checking backend readiness at ${apiUrl}`);
  const readyResponse = await fetchRequired(`${apiUrl.replace(/\/$/, "")}/health/ready`, "backend");
  const ready = await readyResponse.json();
  if (ready.status !== "ready" || ready.database !== "ok") {
    throw new SmokeTestError(`Unexpected backend readiness payload: ${JSON.stringify(ready)}`);
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
