#!/usr/bin/env node

import { cp, mkdir } from "node:fs/promises";
import { existsSync } from "node:fs";

async function copyIfExists(source, destination) {
  if (!existsSync(source)) {
    return;
  }
  await mkdir(destination.replace(/[\\/][^\\/]+$/, ""), { recursive: true });
  await cp(source, destination, { recursive: true, force: true });
}

await copyIfExists(".next/static", ".next/standalone/.next/static");
await copyIfExists("public", ".next/standalone/public");

console.log("Standalone assets prepared");
