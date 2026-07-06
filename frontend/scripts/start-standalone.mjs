process.env.HOSTNAME = process.env.HOSTNAME || "127.0.0.1";
process.env.PORT = process.env.PORT || "3100";

await import("./prepare-standalone.mjs");

console.log(
  `Starting standalone Next server on http://${process.env.HOSTNAME}:${process.env.PORT}`,
);

await import("../.next/standalone/server.js");
