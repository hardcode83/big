import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import openapiTS from "openapi-typescript";

const scriptDirectory = dirname(fileURLToPath(import.meta.url));
const repositoryRoot = resolve(scriptDirectory, "../..");
const sourcePath = join(repositoryRoot, "backend/openapi.json");
const outputPath = join(
  repositoryRoot,
  "frontend/lib/api/generated/openapi.d.ts",
);
const checkMode = process.argv.slice(2).length === 1 && process.argv[2] === "--check";

if (process.argv.slice(2).length > 0 && !checkMode) {
  console.error("Usage: node scripts/generate-api-types.mjs [--check]");
  process.exit(2);
}

function normalizeOutput(value) {
  return `${value.replace(/\r\n?/g, "\n").replace(/\n+$/u, "")}\n`;
}

function printDiff(committed, generated) {
  const committedLines = committed.split("\n");
  const generatedLines = generated.split("\n");
  let firstDifference = 0;

  while (
    firstDifference < committedLines.length &&
    firstDifference < generatedLines.length &&
    committedLines[firstDifference] === generatedLines[firstDifference]
  ) {
    firstDifference += 1;
  }

  const contextStart = Math.max(0, firstDifference - 3);
  const contextEnd = Math.min(
    Math.max(committedLines.length, generatedLines.length),
    firstDifference + 8,
  );

  console.error("--- committed frontend/lib/api/generated/openapi.d.ts");
  console.error("+++ regenerated frontend/lib/api/generated/openapi.d.ts");
  for (let line = contextStart; line < contextEnd; line += 1) {
    if (committedLines[line] !== generatedLines[line]) {
      if (committedLines[line] !== undefined) console.error(`-${committedLines[line]}`);
      if (generatedLines[line] !== undefined) console.error(`+${generatedLines[line]}`);
    } else {
      console.error(` ${committedLines[line]}`);
    }
  }
}

const schema = JSON.parse(await readFile(sourcePath, "utf8"));
const generated = normalizeOutput(
  await openapiTS(schema, {
    alphabetize: true,
  }),
);

if (!checkMode) {
  await writeFile(outputPath, generated, "utf8");
  console.log(`api: generated ${outputPath}`);
  process.exit(0);
}

const temporaryDirectory = await mkdtemp(join(tmpdir(), "autohostai-api-types-"));
const temporaryOutput = join(temporaryDirectory, "openapi.d.ts");

try {
  await writeFile(temporaryOutput, generated, "utf8");
  const committed = await readFile(outputPath, "utf8");
  if (committed === generated) {
    console.log("api: generated types are up to date");
    process.exitCode = 0;
  } else {
    printDiff(committed, generated);
    console.error("api: run npm run api:generate to update the generated artifact");
    process.exitCode = 1;
  }
} finally {
  await rm(temporaryDirectory, { recursive: true, force: true });
}
