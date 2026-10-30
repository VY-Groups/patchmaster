# Documented security exceptions — Stage 0 acceptance gate 2

Plan reference: `plan.md` Stage 0 acceptance criteria — "documented, owner-approved
exceptions". Every entry below is a known, accepted deviation from the Stage 0
security target. Each records: what, evidence, why accepted, owner action, expiry.

Review cadence: this file is re-read at every Stage gate. An entry without a live
owner decision at review time is reopened, not silently carried.

---

## E-1: Secrets in git history (commit `1a033c6`)

**Status:** OPEN — requires owner decision. **Decision deadline:** before any
external repo access (mirrors, forks, CI on public runners).

**What.** Commit `1a033c6` ("chore: save uncommitted changes post v2.5.0
milestone") committed `.pkg-build.otfVRA/.env.production` containing five
populated secrets (verified 2026-10-25 via `git show 1a033c6:.pkg-build.otfVRA/.env.production`):

| Key | Observed length |
|---|---|
| `POSTGRES_PASSWORD` | 65 chars |
| `JWT_SECRET` | 63 chars |
| `LICENSE_SIGN_KEY` | 39 chars (prefix `PatchMaste…`) |
| `OIDC_CLIENT_SECRET` | 52 chars |
| `GF_ADMIN_PASSWORD` | 60 chars |

The file is **removed from the HEAD tree** (verified: `git ls-tree HEAD` for the
path is empty) and `.pkg-build.*` is now gitignored, so it cannot recur. The
values remain reachable via `git log`/`git show` forever.

**Scanner status (2026-10-25).** gitleaks `detect --config .gitleaks.toml`
(history scan): **9 findings, all reachable only through `1a033c6`** — 3 unique
secrets (the `dev-only-…` literal in `backend/auth.py`, an `admin:patchmaster`
credential in `scripts/generate_pdf_guides.py`, and a key in
`packaging/env.example`), each also present under the committed
`.pkg-build.otfVRA/` copy, plus a license token in `LICENSE-INFO.txt`.
Working-tree scan (`--no-git`): **0 findings, exit 0**. CI runs the same
working-tree scope (`gitleaks dir . --config .gitleaks.toml`, ci.yml:106), so
CI stays green; the history scan stays red until E-1 is decided.

**Why accepted (for now).** The repo's only remote is
`github.com/VY-Groups/patchmaster.git` (access-controlled). Rewriting history
destroys every clone reference and must be coordinated; rotation is the
recommended primary mitigation regardless.

**Owner action (choose one, record here):**

- [ ] **Rotate all five values** in every environment that ever used this file,
  then optionally rewrite history. (Recommended: rotation is sufficient and safe.)
- [ ] History rewrite (`git filter-repo` on this path) + force-push + all clones
  re-cloned. Do only after rotation.

**Evidence that HEAD is clean:** `gitleaks dir . --config .gitleaks.toml` →
`no leaks found` (exit 0), 2026-10-25. Note: the CI gate scans the working tree
(`gitleaks dir`), not git history — history scanning is part of the owner
decision above, not currently gated.

**Expiry:** reviewed at Stage 1 gate.

---

## E-2: bandit `nosec` suppressions (3 findings)

**Status:** ACCEPTED — technical debt with in-code justification.

Gate: `bandit -r backend agent -x 'backend/tests' -lll -q` → exit 0
(0 HIGH). Full run: 0 HIGH / 148 results. The three suppressed HIGH findings:

1. `agent/agent.py:172` (zip) and `:186` (tar) — `B202 tarfile/extractall`.
   Justification: `_safe_extract_zip`/`_safe_extract_tar` validate **every
   member** above the `extractall` call (absolute path, symlink/hardlink,
   destination-escape check) and raise on violation. bandit cannot see
   interprocedural validation. Suppression carries a `# reason:` comment on the
   preceding line.
2. `agent/uninstall_agent.py:35` — `B602 subprocess shell=True`. Justification:
   Windows branch only; all 19 `run_cmd` call sites pass hardcoded literal
   commands (verified by grep 2026-10-25), no interpolation.

**Reopen if:** any new caller passes non-literal input to `run_cmd`, or the
extract validation loops are modified. Add a test at that point.

**Expiry:** reviewed whenever `agent/` extraction or uninstall code changes.

---

## E-3: mypy type-check is non-blocking (102 errors / 24 files)

**Status:** ACCEPTED — deferred, visible in CI.

`.github/workflows/ci.yml` runs mypy with `continue-on-error: true`
(`--implicit-optional --ignore-missing-imports --follow-imports=skip
--explicit-package-bases`). Baseline measured 2026-10-25: 129 errors/28 files at
mypy strictness defaults, 102 errors/24 files with `--implicit-optional`
(101 source files checked).

**Why accepted:** flipping it blocking on day one would fail every merge on
pre-existing debt. The job still runs and reports, so new errors are visible.

**Owner action:** clear the backlog, then set `continue-on-error: false` in the
`type-check` job (the `shortcut:` comment in `ci.yml` marks the exact line).

**Expiry:** Stage 1 gate.

---

## E-4: CI e2e live-stack coverage depends on optional `PM_E2E_ENV` secret

**Status:** ACCEPTED — owner configuration pending.

Without the `PM_E2E_ENV` repo secret (full contents of a working `.env`),
`frontend/tests/e2e/real-backend.spec.js` skips itself
(`test.skip(!configured)`), so CI e2e runs only the stubbed specs. First CI run
is therefore green with zero configured secrets — by design, not by accident.

**Owner action:** create repo secret `PM_E2E_ENV` containing a valid `.env`
(`JWT_SECRET`, `PM_SECRET_KEY`, `LICENSE_*`, `POSTGRES_PASSWORD`,
`GF_ADMIN_PASSWORD`, `PM_ADMIN_*`, `PLAYWRIGHT_REAL_*`) to enable live-stack
coverage. Locally this was verified: Playwright 4/4 against the Docker stack,
20/20 HTTP smoke post-credential-rotation (2026-10-25).

**Expiry:** Stage 1 gate — live-stack e2e must be running in CI by then.

---

## E-5: Deferred S0-7 gates

**Status:** RESOLVED (migration test) / ACCEPTED (package build was deferred until verified).

- **Migration test — no longer deferred:** S0-4 delivered the Alembic chain
  (`backend/alembic/versions/20261025_0001_baseline.py`,
  `20261025_0002_legacy_sql_scripts.py`) and
  `backend/tests/test_migrations.py` (fresh install == upgrade-from-previous,
  startup-path `alembic head` + additive reconcile). 5/5 green in the
  CI-fidelity run, 2026-10-26. Gate 3 evidence is live; this entry exists only
  for history.

**No longer deferred — package build:** `packaging/build-package.sh` was
verified end-to-end in a clean `node:22` container (npm ci → frontend build →
package, exit 0; `dist/patchmaster-2.0.17.tar.gz` 12 MB + `.sha256` +
`BUILD-MANIFEST.txt`, 2026-10-25). It is now the blocking `package-build` job
in `.github/workflows/ci.yml`. The bare-metal `install-bare.sh` path was
verified in a Debian container (9/9 assertions, 2026-10-25).

The remaining deferral (type-check) is recorded in the `.github/workflows/ci.yml` header.

**Expiry:** met — S0-4 completed 2026-10-25 (migration test gated in CI).

---

## Sign-off

| Exception | Owner decision | Date |
|---|---|---|
| E-1 git-history secrets | _pending_ | |
| E-2 bandit nosec ×3 | accepted (in-code justification) | 2026-10-25 |
| E-3 mypy non-blocking | accepted (deferred to Stage 1) | 2026-10-25 |
| E-4 optional e2e secret | _pending owner secret configuration_ | |
| E-5 deferred gates | migration test resolved (S0-4 shipped, 5/5 green 2026-10-26); package build gated | 2026-10-26 |
