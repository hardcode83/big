import { existsSync, readFileSync, readdirSync } from "node:fs";
import { resolve } from "node:path";

const buildRoot = resolve(process.cwd(), ".next");
if (!existsSync(buildRoot)) {
  throw new Error("public artifact disclosure gate requires npm run build first");
}

const sentinelValues = [
  process.env.APP_PROVENANCE_REPOSITORY_URL,
  process.env.APP_PROVENANCE_PULL_REQUEST_NUMBER,
  process.env.APP_PROVENANCE_COMMIT_SHA,
  process.env.APP_PROVENANCE_ACTIONS_RUN_ID,
];
if (sentinelValues.some((value) => !value)) {
  throw new Error(
    "public artifact disclosure gate requires all APP_PROVENANCE_* sentinels in the build environment",
  );
}

const sentinels = [
  ...sentinelValues,
  "APP_PROVENANCE_REPOSITORY_URL",
  "APP_PROVENANCE_PULL_REQUEST_NUMBER",
  "APP_PROVENANCE_COMMIT_SHA",
  "APP_PROVENANCE_ACTIONS_RUN_ID",
];

function filesUnder(directory) {
  if (!existsSync(directory)) return [];
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = resolve(directory, entry.name);
    return entry.isDirectory() ? filesUnder(path) : [path];
  });
}

const artifactRoots = ["static", "server", "standalone"].map((part) => resolve(buildRoot, part));
for (const root of artifactRoots) {
  if (!existsSync(root) || filesUnder(root).length === 0) {
    throw new Error(`public artifact disclosure gate found no materialized ${root}`);
  }
}

// These are the actual Next server route outputs. Requiring both route directories prevents
// a green build from silently skipping one of the public surfaces under test.
const requiredRoutes = [
  ["/login", resolve(buildRoot, "server/app/(public)/login")],
  ["/guest/[token]", resolve(buildRoot, "server/app/(guest)/guest/[token]")],
];
for (const [route, directory] of requiredRoutes) {
  const routeFiles = filesUnder(directory);
  if (!routeFiles.some((path) => path.endsWith("/page.js"))) {
    throw new Error(`public artifact disclosure gate found no materialized ${route} page`);
  }
}

// Scan every file in every relevant output root, including generic manifests, server.js,
// RSC payloads and chunks whose names do not mention a route.
const artifacts = artifactRoots.flatMap(filesUnder);
for (const artifact of artifacts) {
  const contents = readFileSync(artifact);
  for (const sentinel of sentinels) {
    if (contents.includes(sentinel)) {
      throw new Error(`private provenance sentinel found in public artifact: ${artifact}`);
    }
  }
}
console.log(`public artifact disclosure: checked ${artifacts.length} artifacts and /login + /guest/[token]`);
