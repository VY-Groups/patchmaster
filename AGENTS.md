# Working rules

## No vibe coding

Do not guess. Every claim about this codebase must come from reading the actual
file, running the actual command, or an MCP tool that reports it. Concretely:

- Before changing a function, read its callers. Grep beats memory.
- Never invent a path, API, config key or version. If it is not verified, say so.
- Do not hand-roll what an installed plugin, skill or MCP server already does.
  This repo has Ponytail (review/audit/debt), Understand-Anything
  (understand/chat/diff/dashboard) and REA (207 local analysis tools) wired in
  `opencode.json`. Reach for them instead of improvising.
- Small non-trivial logic ships with one test or an assert-based self-check.
- Finish the change: callers, tests, fixtures and config your edit breaks.

## This repository

Proprietary patch-management platform. `vendor/` ships to customers — never
place dev tooling there. AI tooling lives in `.tools/` and is documented in
`docs/AGENT_TOOLING.md`.
