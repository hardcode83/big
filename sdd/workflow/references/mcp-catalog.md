# MCP Catalog

Optional MCP servers offered during the init phase. Entries are written in
Claude Code's `.mcp.json` format; translate per tool as described below.
Offer only the ones relevant to the detected stack. Edit this file to add
your own.

## Per-tool wiring

- **Claude Code** — merge entries as-is into the `mcpServers` object of the
  project's `.mcp.json`.
- **opencode** — write into the `mcp` object of the project's `opencode.json`,
  translating: stdio entries (`command` + `args`) become
  `{"type": "local", "command": ["<command>", "<arg1>", ...], "enabled": true}`;
  `http`/`sse` entries become `{"type": "remote", "url": "<url>", "enabled": true}`.
- **Other tools** — most accept one of the two formats above; check the tool's
  MCP docs and translate equivalently.

## github — repo, PRs, issues

Relevant when: the repo is hosted on GitHub. (Note: the `gh` CLI often suffices; offer this only if the user wants richer integration.)

```json
"github": { "type": "http", "url": "https://api.githubcopilot.com/mcp/" }
```

Auth: OAuth prompt on first use, or `Authorization: Bearer <PAT>` header.

## atlassian — Jira & Confluence

Relevant when: the team tracks work in Jira or documents in Confluence.

```json
"atlassian": { "type": "sse", "url": "https://mcp.atlassian.com/v1/sse" }
```

Auth: OAuth browser prompt on first use.

## playwright — browser automation / E2E

Relevant when: frontend or web app projects (verify UI changes during /sdd-run).

```json
"playwright": { "command": "npx", "args": ["@playwright/mcp@latest"] }
```

## context7 — up-to-date library docs

Relevant when: heavy use of fast-moving frameworks/libraries.

```json
"context7": { "command": "npx", "args": ["-y", "@upstash/context7-mcp"] }
```

## postgres — read-only DB inspection

Relevant when: the project uses PostgreSQL and schema questions come up often.

```json
"postgres": { "command": "npx", "args": ["-y", "@modelcontextprotocol/server-postgres", "postgresql://localhost/DBNAME"] }
```

Replace the connection string; prefer a read-only user.

## sentry — error tracking

Relevant when: the project reports errors to Sentry.

```json
"sentry": { "type": "http", "url": "https://mcp.sentry.dev/mcp" }
```

Auth: OAuth browser prompt on first use.
