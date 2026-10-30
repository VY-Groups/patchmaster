# Patch-SecOps Solution Threat Model — STRIDE (Stage 0 / S0-2)

Status: authored 2026-10-25 for plan.md Stage 0 work package S0-2.
Scope: the eight components listed in S0-2. Every claim below is cited to
file:line (verified by reading the code on 2026-10-25; no inferred claims).

Owner column: the repo has a single maintainer account (`@VY-Groups`, verified
via GitHub API 2026-10-25); component labels name the area the owner delegates
to or that fixes the row. Every row is accountable to `@VY-Groups`.
Test column cites tests that exist TODAY; `none (gap)` means no test asserts the
behaviour and that is itself tracked as a finding.

Legend: S=Spoofing, T=Tampering, R=Repudiation, I=Info-disclosure,
D=Denial-of-service, E=Elevation-of-privilege.

---

## 0. Trust boundaries

```
[Browser/SPA] --HTTPS(termination outside repo)-- [Master FastAPI :8000]
     |                                                |
     | JWT (access/refresh)                          | Bearer agent_token (PLAINTEXT HTTP)
     v                                                v
[Master DB PostgreSQL] <--- Fernet(PM_SECRET_KEY) ---[cicd secrets/vault]
                                                       |
                                                       v
                                          [Agent Flask :8080 / Windows :18080]
                                          [metrics :9100 unauthenticated]
[PXE client] --HTTP unauthenticated /boot/*--> [nginx/dnsmasq relay] --agent /run--> [Master]
```

Boundaries: (1) browser→master, (2) master→agent (per-host token, plaintext),
(3) relay public HTTP, (4) vendor license signing→customer instance,
(5) upstream package mirrors→master content store.

---

## 1. Master API (FastAPI, `backend/`)

Auth model: HS256 access JWT, fail-closed secret (`backend/auth.py:22-49`),
role gate `require_role` (`backend/auth.py:236-247`), pbkdf2_sha256 passwords
(`backend/auth.py:56`), lockout after 5 attempts/15 min
(`backend/api/auth_api.py:51-52`, 429 at `:214-228`).

| # | Threat (STRIDE) | Mitigation (current) | Owner | Test / evidence |
|---|---|---|---|---|
| M1 | **S** — forge access token with default/known JWT secret | `_load_jwt_secret` rejects missing, <32 chars, and all shipped placeholders else `RuntimeError` (`backend/auth.py:22-49`); `type=="access"` enforced (`backend/auth.py:197-198`) | backend | `tests/test_jwt_secret_fail_closed.py` (7 tests incl. subprocess boot failure); FAIL→PASS proven 2026-10-25 |
| M2 | **S** — brute-force password guessing | lockout 5/15 min → 429 + Retry-After (`backend/api/auth_api.py:214-228`, `:330-341`); dummy-hash timing equalization (`:319-325`); slowapi decorator on login (`:307-308`) | backend | **none (gap)** — no lockout/rate-limit test exists; see finding F1 |
| M3 | **E** — viewer performs destructive route (reboot, patch, delete) | `require_role(admin, operator)` on 30+ mutating routes (`backend/auth.py:236-247`) | backend | `tests/test_rbac_destructive.py` (viewer 403 ×30+, admin allowed, reads stay open) |
| M4 | **I** — session survives password change / theft of refresh token | refresh tokens SHA-256 hashed, rotated per use, all revoked on password change (`backend/auth.py:118-181`) | backend | `tests/test_auth_security.py:141-150`; `test_rbac_destructive.py:153-170` |
| M5 | **I** — token leak via cookie on plain-HTTP deployment | cookies `httponly`, refresh `samesite=strict` scoped to `/api/auth/refresh` (`backend/api/auth_api.py:362-394`) | backend | `tests/test_auth_security.py` (reset-purpose JWT rejected `:117`) |
| M6 | **T** — first-run takeover: unauthenticated bootstrap of admin | `POST /api/auth/register` allowed only when user count == 0 (`backend/api/auth_api.py:607-629`); `ensure_bootstrap_users` from `PM_ADMIN_*` env when DB empty (`backend/bootstrap_users.py:56-87`) | backend | `tests/test_bootstrap_users.py` |
| M7 | **E** — CSRF on OIDC callback | one-shot `state` token stored/checked (`backend/api/oidc_auth.py:116-131`) | backend | **none (gap)** |
| M8 | **I** — GraphQL bypasses route-level auth | whole router mounted `dependencies=[Depends(get_current_user)]` (`backend/api/graphql.py:291-302`) | backend | `tests/test_graphql_auth.py` (401 missing/garbage, 200 valid) |
| M9 | **D** — request flooding beyond lockout (no IP throttle) | `RateLimitMiddleware` defined (`backend/middleware/rate_limit.py:18-43`) **but never registered** (`backend/main.py:518-538` only adds License/MultiTenant/Metrics/Trace/CORS) | backend | **none (gap)** — see finding F2; `.planning/…/06-01-VERIFICATION.md:28` wrongly claims it active |
| M10 | **I** — missing security headers (CSP/HSTS/frame) | `SecurityHeadersMiddleware` defined but unregistered (`backend/middleware/security.py:16`); headers partially emitted inside `LicenseMiddleware.add_security_headers` (`backend/main.py:485-509`) | backend | **none (gap)** — see finding F3 |
| M11 | **S** — CORS `*` reflects any origin with credentials off | `FRONTEND_ORIGINS` default `"*"`, `allow_credentials` only when origins != `["*"]` (`backend/main.py:529-538`) | backend | **none (gap)** — deploy note: set `FRONTEND_ORIGINS` explicitly in prod compose |
| M12 | **R/I** — websocket accepts refresh-purpose JWT | notifications `/ws` decodes JWT but skips `type=="access"` check (`backend/api/notifications.py:207-208` vs `backend/auth.py:197-198`) | backend | **none (gap)** — see finding F4 |
| M13 | **I/E** — job-status websocket streams job data with **zero auth** | `accept()` then only `isdigit()` check (`backend/api/jobs_v2.py:446-482`) | backend | **none (gap)** — see finding F5 (highest-severity code gap found in S0-2) |

---

## 2. Agent API (token-authenticated Flask, `agent/agent.py`)

Auth model: `@_require_auth` decorator, `hmac.compare_digest` against 0–2
tokens (env `AGENT_API_TOKEN` + per-host `STATE_DIR/token` file); **no token →
503 fail-closed** (`agent/agent.py:84-147`). Plain HTTP, port 8080/18080
(`agent/agent.py:4598-4604`).

| # | Threat (STRIDE) | Mitigation (current) | Owner | Test / evidence |
|---|---|---|---|---|
| A1 | **S** — master calls agent with guessed/stolen token | constant-time `hmac.compare_digest` over all valid tokens (`agent/agent.py:140-144`); unconfigured agent → 503 (`:133-134`) | agent | **none (gap)** — no agent-side `_require_auth` test exists (finding F6) |
| A2 | **T** — agent executes catastrophic command via `/run` | `_BLOCKED_CMDS` regex blocks `rm -rf /`, `mkfs`, `dd if=`, fork bomb, shutdown (`agent/agent.py:4532-4557`) | agent | guarded by master-side allowlist too (see L2) |
| A3 | **T** — path traversal via archive upload to agent | `_safe_extract_zip/_safe_extract_tar` validate abs path/symlink/link/escape before `extractall` (`agent/agent.py:160-188`) | agent | bandit nosec justified: `docs/security/exceptions.md` E-2 |
| A4 | **I** — unauthenticated recon routes leak host detail | 12 routes lack `@_require_auth`: `/health` (hostname/OS/version, `:2057-2076`), `/api/debug/memory` (`:2092-2114`), `/api/version`, `/status`, `/job/history`, `/snapshot/list`, `/packages/*`, `/wsus/status` | agent | **none (gap)** — see finding F7 |
| A5 | **I** — metrics port 9100 world-readable | `start_http_server(metrics_port)` no auth (`agent/agent.py:4599`) | agent | accepted: metrics scrapers need open read; document bind to localhost/LAN (finding F8) |
| A6 | **T** — token file readable by other local users | written `chmod 0600` (`agent/main.py:464-470`) | agent | **none (gap)** |
| A7 | **D** — no rate limit on agent endpoints | none | agent | **none (gap)** — mitigated by per-host token + LAN scope; revisit with mTLS (T7) |

---

## 3. Agent proxy (master → agent, `backend/api/agent_proxy.py`)

Outbound path: `http://{ip}:{port}{path}` with `Authorization: Bearer <host.agent_token>`
(`backend/api/agent_proxy.py:67-110`); SSRF guard `_validate_host_ip` requires
valid IP **and** a hosts-table row (`:91-102`).

| # | Threat (STRIDE) | Mitigation (current) | Owner | Test / evidence |
|---|---|---|---|---|
| P1 | **T** — proxy reaches arbitrary internal host (SSRF) | `_validate_host_ip` before every proxy call (`:91-102`, called `:194`, `:217`, `:258`, `:289`…) | backend | **none (gap)** — no dedicated SSRF test (finding F9) |
| P2 | **S** — replay/capture of agent token on the wire | master↔agent is **plaintext HTTP** (`:105-110`, `agent/agent.py:4604`); token never leaves without Bearer header, but network sniffing sees it | agent/infra | accepted for LAN fleets; see trust-model decision TM4 (TLS) |
| P3 | **E** — viewer triggers reboot/shutdown/patch through proxy | `require_role(admin, operator)` on mutating proxy routes (`:287`, `:297`, `:751`, `:881`) | backend | `tests/test_rbac_destructive.py:46-69` |
| P4 | **T** — redirect from agent pivots proxy (follow_redirects) | `_get_stream` follows redirects without re-validating target (`:226-227`) | backend | **none (gap)** — finding F10: set `follow_redirects=False` or re-validate |
| P5 | **E** — empty header set when neither token configured | falls back to `{}` (`:79-81`); agent side then 503 → fails **closed** | backend | verified in code path; **none (gap)** as a test |

---

## 4. Live-command console (`POST /api/agent/{ip}/run`)

Not a websocket — HTTP route gated `require_role(admin, operator)` + kill
switch `LIVE_CMD_ENABLED` + prefix allowlist + audit
(`backend/api/agent_proxy.py:1484-1691`).

| # | Threat (STRIDE) | Mitigation (current) | Owner | Test / evidence |
|---|---|---|---|---|
| L1 | **E** — viewer runs arbitrary commands on hosts | `require_role(admin, operator)` (`:1617`, `:1674`) + redundant inline check (`:1624`, `:1678`) | backend | `tests/test_rbac_destructive.py` (route in destructive list) |
| L2 | **T** — destructive command through console | strict prefix allowlist `_ALLOWED_CMD_PREFIXES` (`df`,`du`,`ps`,`cat`…, `:1488-1562`) enforced (`:1630-1635`) + agent-side blocklist (A2) | backend | **none (gap)** — no allowlist test (finding F11) |
| L3 | **D** — long-running command ties host | timeout clamped 1–300 s (`:1636-1637`) | backend | **none (gap)** |
| L4 | **R** — operator denies running a command | every execution audited as `live_command` (`_audit_command` `:1567-1590`, called `:1639`, `:1691`) | backend | audit module covered indirectly; **none (gap)** for live_command rows |
| L5 | **E** — console disabled can be re-enabled by env attacker | `LIVE_CMD_ENABLED` kill switch (`:1484`) is env-controlled — whoever controls env controls it (env is trusted boundary) | infra | n/a — env is inside trust boundary |

---

## 5. License engine (`backend/license.py`, `backend/api/license_router.py`)

PM2-only licenses: Ed25519 verify first, legacy HMAC-SHA256 fallback with
`LICENSE_SIGN_KEY`; signature checked **before** decrypt (X25519+HKDF+AES-256-GCM);
hw binding to MAC unless `no_bind` (`backend/license.py:299-473`).
`LicenseMiddleware` 403s invalid/expired/unactivated and gates features
(`backend/main.py:345-462`).

| # | Threat (STRIDE) | Mitigation (current) | Owner | Test / evidence |
|---|---|---|---|---|
| C1 | **E** — forge license to unlock paid tiers | Ed25519 verify (`license.py:304-314`) + payload sealed to server public key (`:357-383`) + PM2-only (`:429-430`); placeholders rejected (`:30-44`) | release | `tests/test_master.py:209-293` (PM1 rejected, PM2 accepted, binding enforced) |
| C2 | **E** — HMAC fallback weakens signing | legacy HMAC path live **if** `LICENSE_SIGN_KEY` configured (`:321-335`); compose requires it (`docker-compose.yml:28`); placeholder value in `.env.production:22` is rejected (`license.py:34`) | release | accepted risk tracked: `docs/security/exceptions.md` E-1 (history secret) — **decision: deprecate HMAC path in Stage 1** (TM5) |
| C3 | **T/E** — copy a licensed instance's payload to another host | hw binding `hw_id` must match local MAC or `PM_BINDING_ID` (`:456-473`) | release | `tests/test_master.py:257-293` |
| C4 | **I** — license status unauthenticated | `GET /api/license/status` no auth (`license_router.py:60-61`) | backend | accepted: status carries no secret (tier/activated flag only); revisit if it exposes keys |
| C5 | **E** — bypass activation by calling exempt path | exemption list is health/register/heartbeat/license/auth/boot/static/metrics/graphql (`main.py:347-360`); feature paths all behind `FEATURE_PATH_MAP` (`:363-449`) | backend | `tests/test_license_middleware.py:27-48` (exempt + blocked paths) |

---

## 6. Content import (`backend/api/mirror_repos.py`, `packages_router.py`, `cicd.py`)

Mirror sync pulls package catalogs/downloads; roles admin/operator for
sync/create, admin for delete (`mirror_repos.py:1207-1429`); local upload
extension allowlist (`packages_router.py:167-184`).

| # | Threat (STRIDE) | Mitigation (current) | Owner | Test / evidence |
|---|---|---|---|---|
| N1 | **T** — upstream mirror serves tampered package | **checksums recorded but NEVER verified** on download (`mirror_repos.py:784-801`; `:769/:777` copy only) | backend | **none (gap)** — finding F12 (top integrity gap): verify sha256 before serving to agents |
| N2 | **T** — malicious filename escapes repo dir | `os.path.basename` (`:788-792`), `_safe_dir_name` alnum/-/_ only (`:361-363`) | backend | **none (gap)** for mirror path |
| N3 | **T** — path traversal on package push to host | `POST /push/{host_id}` joins **raw** filename to `LOCAL_REPO_DIR` with no basename (`packages_router.py:186-201`) | backend | **none (gap)** — finding F13 |
| N4 | **T** — unauthenticated CI/CD artifact read **and path traversal** | `GET /api/cicd/artifacts/{build_id}/{filename}` has no auth dependency and joins the raw `filename` onto the artifacts dir (`cicd.py:2607-2612`, traversal at `:2609` via `../`) | backend | **none (gap)** — finding F14 |
| N5 | **T** — upload with crafted filename writes outside target | artifacts upload writes `target_dir / filename` raw (`cicd.py:2582-2594`); local upload allowlists extension + basename (`packages_router.py:167-184`) | backend | **none (gap)** — finding F15 (basename needed on cicd upload) |
| N6 | **E** — viewer imports content | import/sync endpoints `require_role(admin, operator)`; delete admin-only (`:1336`); CVE import gated (`cve.py:424-429`) | backend | part of RBAC suite |
| N7 | **I** — mirror credential leak in outbound call | creds decrypted server-side only for the outbound request (`mirror_repos.py:726-729`), never returned by API (vault, section 8) | backend | vault tests (V2) |

---

## 7. Relay (PXE / network boot, `backend/api/network_boot.py`)

Master renders dnsmasq+nginx bundles; relay host installs via agent `/run`;
PXE-facing endpoints are public by design.

| # | Threat (STRIDE) | Mitigation (current) | Owner | Test / evidence |
|---|---|---|---|---|
| R1 | **E** — unauthenticated control of relay management | management API `POST /relays`, `/install|/sync|/validate` → `require_role(admin, operator)` (`:1616-1620`, `:1699-1723`); reads `get_current_user` (`:1604-1605`) | backend | `tests/test_network_boot.py` (95 lines covered) |
| R2 | **I** — relay bundle pulled by unauthorized party | `GET /boot/…/bundle.tar.gz` public, no auth (`:2184-2239`) — dnsmasq config + iPXE scripts; contains no secrets but reveals topology | infra | accepted (PXE clients cannot authenticate); **decision: bind bundle URL to per-relay session token in Stage 1** (TM6) |
| R3 | **S** — boot-session hijack | session token uuid4 hex minted (`:1235`) and validated on events (`:1773-1775`); `POST /events` otherwise unauthenticated | backend | `tests/test_network_boot.py` |
| R4 | **T** — boot-answer tampering | answers are stateless booted client metadata; validated shape only (`:2270-2311`) | backend | **none (gap)** |
| R5 | **E** — installing relay runs arbitrary host commands | install/sync executed **through** agent `/run` with per-host Bearer (`:1376-1395`) → inherits agent allowlist (L2/A2) | agent/infra | inherits L2 controls |
| R6 | **I** — relay bundle over plaintext HTTP | `public_base_url = f"http://{host.ip}"` default (`:1640`) | infra | **decision: HTTPS base URL required for non-lab installs** (TM4) |

---

## 8. Vault / secrets (`backend/api/cicd_secrets.py`)

Fernet key from `PM_SECRET_KEY`, fail-closed; key lives only in process env
(never DB); API returns `has_value` booleans only — no endpoint ever returns
plaintext (`cicd_secrets.py:49-360`).

| # | Threat (STRIDE) | Mitigation (current) | Owner | Test / evidence |
|---|---|---|---|---|
| V1 | **I/E** — read stored secrets back via API | `_to_out` returns `has_value` only (`:233-244`); no GET returns plaintext; plaintext only in internal `resolve_secrets_for_pipeline` (`:347-360`) | backend | `tests/test_cicd*.py` — verify exact file; API shape asserted in RBAC list |
| V2 | **S** — secrets decryptable without server key | Fernet key fail-closed if `PM_SECRET_KEY` unset (`:51-55`); key never stored in DB | backend | fail-closed asserted via code; **none (gap)** as dedicated test |
| V3 | **T** — weak key derivation trivially brute-forced | non-32-byte values re-derived as `SHA-256(value)` (`:63-66`) — a *passphrase* becomes the key (low entropy risk) | backend | accepted: installers generate 32-byte random keys (`install-bare.sh`, `install_patchmaster_docker.sh:40`); **finding F16: warn on low-entropy key** |
| V4 | **E** — viewer reads/creates secrets | list/create/update `require_role(admin, operator)`; delete admin-only (`:249-335`) | backend | `tests/test_rbac_destructive.py` |
| V5 | **R** — secret used without trace | secret values themselves never logged (helpers only encrypt/decrypt in memory, `:70-82`) | backend | **none (gap)** — log-scrub assertion test planned |

---

## Agent trust model (S0-2 decision)

**TM1 — Per-host tokens: RETAIN.** Registration mints `uuid4` per host, stored
`hosts.agent_token` (`register_v2.py:366`, `:411-425`), presented as Bearer on
every master→agent call (`agent_proxy.py:67-81`) and agent→master callback
(`backups.py:229-256`, `agent/agent.py:229-248`). Rationale: revoking one host
must not kill the fleet; per-host scope gives that.

**TM2 — First registration stays unauthenticated by design** (bootstrap), with
the credential gate: an *already-tokened* host requires the current token or
the operator `AGENT_API_TOKEN` else 401 (`register_v2.py:377-387`). Residual
risk: an attacker on the network can register a *new* host identity. Accepted
for Stage 0 (air-gapped fleets); Stage 1 adds a one-time enrolment token
(the code comment at `register_v2.py:378-381` already plans this). **Owner:
backend. Deadline: Stage 1 gate.**

**TM3 — Rotation & revocation: document current mechanics, add explicit
endpoint in Stage 1.** Today rotation is implicit: presenting
`AGENT_API_TOKEN` on `/api/register` re-mints (`register_v2.py:403-406`, tested
`test_register_auth.py:123-128`), and an agent receiving 401 clears its token
and re-registers (`agent/main.py:504-519`). Revocation = clearing
`hosts.agent_token` (agent then 401s and falls to re-register gate). No
`/rotate` or `/revoke` endpoint exists. **Decision: Stage 1 delivers
`POST /api/hosts/{id}/agent-token/rotate` and `/revoke` (admin-only) plus a
heartbeat constant-time compare** (current `!=` at `register_v2.py:384`,
`:485` — finding F17). Owner: backend.

**TM4 — mTLS option: DEFERRED with a staged plan.** No `ssl_context`/client
cert exists anywhere (verified grep: only outbound TLS *verification toggles*,
e.g. `git_integration.py:28`, `ldap_auth.py:79`). Master↔agent is plaintext
HTTP (`agent_proxy.py:105-110`). Decision:
- Stage 0 (now): deployments that cross untrusted networks terminate TLS at a
  reverse proxy for the master; agent fleets stay on segmented LAN/VLAN.
- Stage 1: optional agent-side TLS (`ssl_context` on `app.run`, certs
  provisioned alongside the token) — mutual auth becomes token+TLS.
- Stage 2: full mTLS with per-host client certs replacing bearer tokens.
Rationale for staging: agents ship to classified/dark sites where an internal
CA is a customer-controlled dependency; forcing mTLS now would break existing
installs. Owner: agent + release.

**TM5 — Deprecate HMAC license signing.** The `LICENSE_SIGN_KEY` symmetric
fallback (`license.py:321-335`) is forge-capable if the key leaks (and it did,
E-1). Stage 1: Ed25519-only verification with a transition flag. Owner: release.

**TM6 — Relay bundle URL gains a per-relay token** so topology isn't readable
anonymously (`network_boot.py:2184-2239`). Owner: backend. Stage 1.

---

## Findings register (gaps discovered while writing this model)

Severity: H=fix before Stage 1 gate, M=Stage 1, L=backlog.

| ID | Sev | Finding | Evidence | Status |
|---|---|---|---|---|
| F5 | **H** | Job websocket has no authentication at all | `jobs_v2.py:446` (pre-fix `:446-482`); fixed by auth gate, test `tests/test_s02_endpoint_auth.py` | fixed 2026-10-25 |
| F12 | **H** | Mirror package downloads never checksum-verified | `mirror_repos.py:784-801` | open |
| F13 | **H** | `/api/packages/push/{host_id}` raw filename join (traversal) | `packages_router.py` push handler (pre-fix join `:201`); fixed with `validate_filename()` | fixed 2026-10-25 |
| F14 | **H** | CI/CD artifact GET unauthenticated + raw filename join (traversal) | `cicd.py` download handler (pre-fix `:2607-2612`); fixed with `get_current_user` + `validate_filename()` | fixed 2026-10-25 |
| F15 | **H** | CI/CD artifact upload writes raw client filename | `cicd.py` upload handler (pre-fix `:2582-2594`); fixed with `validate_filename()` | fixed 2026-10-25 |
| F1 | M | No test for login lockout / rate limit | grep of `backend/tests` | open |
| F2 | M | `RateLimitMiddleware` defined, never registered | `middleware/rate_limit.py:43` vs `main.py:518-538` | open |
| F3 | M | `SecurityHeadersMiddleware` never registered | `middleware/security.py:16` | open |
| F4 | M | Notifications WS skips `type=="access"` check | `notifications.py` `_resolve_websocket_user` (added); also gates job WS | fixed 2026-10-25 |
| F6 | M | No agent-side `_require_auth` test | grep in `agent/` tests | open |
| F7 | M | 12 unauthenticated agent info routes incl. `/api/debug/memory` | `agent/agent.py:2057-2114` | open |
| F9 | M | No SSRF test for proxy host validation | `agent_proxy.py:91-102` | open |
| F10 | M | `_get_stream` follows redirects without revalidation | `agent_proxy.py:226-227` | open |
| F11 | M | No test for live-command prefix allowlist | `agent_proxy.py:1488-1609` | open |
| F16 | L | Low-entropy `PM_SECRET_KEY` silently accepted | `cicd_secrets.py:63-66` | open |
| F17 | L | Non-constant-time token compares master-side | `register_v2.py:384`, `:485` | open |
| F8 | L | Agent metrics port 9100 unauthenticated | `agent/agent.py:4599` | open (documented bind scope) |
| F18 | M | Login with an unknown username returned HTTP 500 (malformed timing-equalization dummy hash) | `auth_api.py` `login` (pre-fix `:321`); test `tests/test_s02_endpoint_auth.py` | fixed 2026-10-25 |

Each finding above was observed while reading code for this model; this
document fixes nothing by itself. Rows marked `fixed 2026-10-25` were closed
with FAIL→PASS evidence in `backend/tests/test_s02_endpoint_auth.py` (F4, F5,
F13, F14, F15, F18 — six findings); everything else stays open with the owner
and stage named above. Findings are the S0-2 output the plan asks for ("each
threat, mitigation, owner and test" — where test says `none (gap)` the finding
row is its tracking entry).

---

## Owner actions summary (single accountable: @VY-Groups)

1. **Now:** decide E-1 (git-history secrets) — rotate vs rewrite
   (`docs/security/exceptions.md`).
2. **Stage 1 gate:** F5, F12, F13, F14, F15 (H-sev); TM2 enrolment token; TM3
   rotation/revocation endpoints; TM4 TLS stage 1; TM5 HMAC deprecation.
3. **Stage 1:** convert F1–F11, F16–F17 into issues or tests; each `none (gap)`
   test cell must gain a test or an accepted-exception entry in
   `docs/security/exceptions.md`.
