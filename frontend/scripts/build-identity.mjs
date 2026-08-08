import { appendFileSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const scriptDirectory = dirname(fileURLToPath(import.meta.url));
const contractPath = resolve(
  scriptDirectory,
  "../lib/config/build-identity-contract.json",
);
const contract = JSON.parse(readFileSync(contractPath, "utf8"));

const BASE = new RegExp(`^${contract.basePattern}$`);
const DATE = new RegExp(`^${contract.datePattern}$`);
const COMMIT_SHORT = new RegExp(`^${contract.commitShortPattern}$`);
const PRODUCTION_VERSION = new RegExp(
  `^${contract.basePattern}\\+${contract.datePattern}\\.${contract.commitShortPattern}$`,
);
const VERSION_DATE = new RegExp(
  `^${contract.basePattern}\\+(${contract.datePattern})\\.${contract.commitShortPattern}$`,
);
const TIMESTAMP = /^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2}):(\d{2})Z$/;

function realCalendarDate(date) {
  const [yearText, monthText, dayText] = date.split("-");
  const year = Number(yearText);
  const month = Number(monthText);
  const day = Number(dayText);
  if (!Number.isSafeInteger(year)) return false;

  const daysInMonth = [
    31,
    year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0) ? 29 : 28,
    31,
    30,
    31,
    30,
    31,
    31,
    30,
    31,
    30,
    31,
  ][month - 1];
  return day <= daysInMonth;
}

function assertTimestamp(value) {
  const match = TIMESTAMP.exec(value);
  if (!match || !realCalendarDate(match[1])) {
    throw new Error("built_at must be a real UTC timestamp YYYY-MM-DDTHH:MM:SSZ");
  }

  const [, date, hours, minutes, seconds] = match;
  if (Number(hours) > 23 || Number(minutes) > 59 || Number(seconds) > 59) {
    throw new Error("built_at must contain a valid UTC time");
  }
  if (!DATE.test(date)) {
    throw new Error("built_at date does not satisfy the public date contract");
  }
}

export function validateBuildIdentity({ version, commitShort, builtAt, repoUrl = "" }) {
  if (!COMMIT_SHORT.test(commitShort)) {
    throw new Error("commit_short must contain exactly 7 lowercase hexadecimal characters");
  }
  if (!PRODUCTION_VERSION.test(version)) {
    throw new Error("version must have the form X.Y.Z+YYYY-MM-DD.<7 hex>");
  }
  const versionDate = VERSION_DATE.exec(version)?.[1];
  if (!versionDate || !realCalendarDate(versionDate)) {
    throw new Error("version must contain a real calendar date");
  }
  const versionCommit = version.slice(version.lastIndexOf(".") + 1);
  if (versionCommit !== commitShort) {
    throw new Error("version and commit_short must contain the same short commit");
  }
  assertTimestamp(builtAt);
  if (repoUrl.includes("\n") || repoUrl.includes("\r")) {
    throw new Error("repo_url must not contain line breaks");
  }
  return { version, commitShort, builtAt, repoUrl };
}

export function composeBuildIdentity({ base, sha, builtAt, repoUrl = "" }) {
  const normalizedBase = base.trim();
  if (!BASE.test(normalizedBase)) {
    throw new Error("VERSION must have the form X.Y.Z");
  }
  if (!/^[0-9a-f]{40}$/.test(sha)) {
    throw new Error("GITHUB_SHA must contain 40 lowercase hexadecimal characters");
  }
  assertTimestamp(builtAt);

  const commitShort = sha.slice(0, 7);
  const version = `${normalizedBase}+${builtAt.slice(0, 10)}.${commitShort}`;
  return validateBuildIdentity({ version, commitShort, builtAt, repoUrl });
}

function main() {
  const outputPath = process.env.GITHUB_OUTPUT;
  if (!outputPath) throw new Error("GITHUB_OUTPUT is required");

  const versionPath = process.env.VERSION_FILE ?? resolve(scriptDirectory, "../../VERSION");
  const base = readFileSync(versionPath, "utf8").replace(/\s/g, "");
  if (!base) throw new Error("VERSION is empty");

  const builtAt = new Date().toISOString().replace(/\.\d{3}Z$/, "Z");
  const repoUrl = `${process.env.GITHUB_SERVER_URL ?? ""}/${process.env.GITHUB_REPOSITORY ?? ""}`;
  const identity = composeBuildIdentity({
    base,
    sha: process.env.GITHUB_SHA ?? "",
    builtAt,
    repoUrl,
  });

  appendFileSync(
    outputPath,
    `version=${identity.version}\ncommit_short=${identity.commitShort}\nbuilt_at=${identity.builtAt}\nrepo_url=${identity.repoUrl}\n`,
  );
}

const invokedPath = process.argv[1] ? resolve(process.argv[1]) : "";
if (invokedPath === fileURLToPath(import.meta.url)) {
  try {
    main();
  } catch (error) {
    console.error(`::error::${error instanceof Error ? error.message : String(error)}`);
    process.exitCode = 1;
  }
}
