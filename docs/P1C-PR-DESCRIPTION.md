# P1-C: layer boundaries and transactional control (COD-09, COD-11)

PR body content for the orchestrator to use when opening the pull request.

## Target and merge policy (read first)

- **Target branch:** this PR targets the fork's OWN `main`
  (`joaovitormiranda-eng/bootcamp-qitech-bank-api`). It does **NOT** target the
  upstream `mohamad347/bootcamp-qitech-bank-api`.
- **No auto-merge.** Do not enable auto-merge. Merge only after a human review
  and a green CI run.
- Source branch: `refactor/p1c-layer-boundaries-transactions`.

## Summary

P1-C resolves two localized architecture findings in the transaction path with
zero change to observable API behavior and zero DB schema change.

### COD-09: layer boundary (fee/hash moved out of the controllers package)

Two pure modules that lived inside `src/controllers/` but are not controllers
were moved into a new non-controller `services` package:

- `src/controllers/transaction_fee.py` -> `src/services/transfer_fee.py`
- `src/controllers/transaction_hash.py` -> `src/services/transaction_hash.py`

`src/controllers/transaction_controller.py` now imports these helpers
**downward** from `services.*` instead of **sideways** from its own package. The
old `controllers.transaction_fee` / `controllers.transaction_hash` import paths
no longer resolve. The two unit tests that pinned the old paths were updated to
the new ones. A flat `services` package was chosen over leaving the modules in
`controllers` (keeps the smell) and over inventing deeper layers (rejected under
the "no artificial layers / no over-abstraction" guardrail).

### COD-11: transactional control (commit made visible at the public boundary)

The single `session.commit()` for the financial flows was hidden two call levels
down in a private helper (`_commit_and_build_response`). It is now a **visible
line in the public `create()` method**, matching the other three controllers
which all commit as the last persistence step of their public method. The
private flows (`_create_deposit`, `_create_transfer`) return the staged
transaction key (new work) or the replay response (replay); the public method
commits exactly once for new work and commits nothing on replay or conflict. The
private helper was removed; a `_build_response` helper does the post-commit
re-read + DTO projection.

Key constraints honored:

- Exactly **one** commit per successful op; no intermediate/duplicate commits.
- The middleware (`src/middlewares/session_manager.py`) still **never** commits;
  moving the commit into the middleware was explicitly avoided.
- `src/database.py` Context/session lifecycle is **unchanged**.
- The deliberate `rollback()`-before-external-HTTP in `client_analysis.analyze`
  and the `rollback()`-on-replay in the transaction flows are preserved exactly.

## Scope guardrails honored

- Observable API behavior: unchanged.
- DB: no schema/table/column/enum/migration change (`database/database.sql`
  untouched).
- No new banking features; no deleted tests, no weakened assertions, no
  skip/xfail added.
- Changes confined to: the two moved modules, their two importing/consuming
  sites, the two unit tests pinning the old paths, the new tests, and docs.

## Invariants preserved

Money in integer cents; PF fee 0.50% min 50 max 1000; PJ fee 1.00% min 100 max
1500; HALF_UP rounding; Idempotency-Key UUID + SHA-256 intent hash; idempotent
replay + conflict (409 TRX0003); account locks in ascending `ACCOUNT.id` order;
no negative balance; atomicity of source/dest/fee/history/idempotency as one
unit; full rollback on failure; statement dates/order/pagination/timezone;
MockServer cadastral integration; HTTP contracts and RFC error codes. See
`docs/P1C-ARCHITECTURE-AUDIT.md` Section 8 for the invariant-to-test mapping.

## Test delta

- Collection: **506 -> 521** (+15 new tests; no test lost).
- New tests: 11 pure unit (5 in `tests/unit/test_services_layer_boundary.py`
  incl. a parametrized legacy-module-missing check, 6 in
  `tests/unit/test_transfer_fee_invariants.py`) + 4 integration
  (`tests/integration/transaction/r07_safety/test_commit_boundary.py`:
  single-commit deposit, single-commit transfer, idempotent-replay-no-new-work,
  incompatible-key-409-no-new-work).
- Host unit tests: **23 -> 34** passing (the 11 new pure unit tests; the 4 new
  integration tests are Docker/CI-only).

## How to validate

- **CI is authoritative.** Docker is unavailable in the development sandbox, so
  the full integration suite (including the 4 new commit-boundary tests) runs
  only in GitHub Actions (`.github/workflows/ci.yml`). There is no lint step in
  CI; the sole gate is pytest. Confirm the Actions run on the PR head commit is
  green before merging.
- Local (host, pure unit only):
  - `.venv/bin/python -m pytest --collect-only -q | tail -1` -> `521 tests collected`.
  - `cd src && ../.venv/bin/python -m pytest ../tests/unit -q` -> `34 passed`.
- CI / Actions run: _PLACEHOLDER (orchestrator fills after push)_
- Validated commit SHA: _PLACEHOLDER (orchestrator fills after push)_
