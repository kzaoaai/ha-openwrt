@AGENTS.MD

# Fork notes (kzaoaai/ha-openwrt)

This file exists only on the fork's `all-changes` branch. Never let it reach a branch meant
for an upstream PR.

## What this is

The owner's fork of `FaserF/ha-openwrt`, the HACS integration for OpenWrt routers.
Remotes: `origin` = the fork, `upstream` = FaserF (PRs target it). The owner's production
Home Assistant runs the upstream **HACS release** with the fork's `all-changes` build
swapped over its files.

## Branches

- `all-changes`: what prod runs. Always **the latest upstream release tag** + the owner's
  unmerged fix branches (cherry-picked) + this file's commit. Never base it on `upstream/main`:
  unreleased main crashed every router on HA 2026.9 on 2026-09-28.
- `fix/*`: one per upstream PR candidate, cut from freshly fetched `upstream/main`.
- `main` on the fork is stale (May 2026) and is never a base for anything.

## Test

- Repo suite: `tests/conftest.py` replaces Home Assistant with mocks, so it runs in a plain
  venv: `pip install pytest pytest-asyncio voluptuous aiohttp paramiko pyyaml segno ruff`,
  then `pytest -q tests` and `ruff check custom_components tests`. The three
  `tests/test_gps_location.py` errors happen on clean upstream too in that env.
- Because the suite mocks HA, it cannot catch HA API breakage. **Before any build goes to
  prod**, set it up on real HA at prod's exact version with
  `pytest-homeassistant-custom-component` pinned to that version, and run plain upstream as a
  control. Recipe: memory note `verify-on-real-ha-before-prod`.
- Test fixtures use documentation addresses: MACs `00:00:5e:00:53:xx`, IPs `192.0.2.x`.
  Placeholders like `aa:bb:…` have the locally-administered bit set and get dropped by the
  random-MAC filter (`helpers.is_random_mac`), which silently changes what a test exercises.

## Deploy

HACS cannot install a fork branch under the upstream entry, so: update the upstream release
in HACS first (keeps HACS's record honest), then swap `git archive all-changes
custom_components/openwrt` into `/config/custom_components/openwrt` with the manifest
`version` set to the release, and md5-verify against git. The owner restarts HA; never
restart it from a session. Host access, the exact steps and the rollback copy: memory note
`ha-openwrt-all-changes-deploy`.

## Things the code does not tell you

- HA ≥ 2026.9: a device belongs to exactly one config entry; iterating `registry.devices`
  yields `DeviceEntry` objects, not ids; `async_get_device` is deprecated in favour of
  `async_get_device_by_identifier(identifier, config_entry_id)`; removal is
  `async_remove_device`, not `remove_config_entry_id`.
- luci-mod-rpc 26.x's `auth` endpoint has only `challenge` and `login`. There is no logout,
  so a client cannot destroy its rpcd session; sessions just expire.

## Current state and open items

- `all-changes`: v2.5.3 + this file only, so its integration code is identical to the
  v2.5.3 release. v2.5.3 (2026-10-11) carries every fork fix: LuCI reauth
  (FaserF/ha-openwrt#159), the gateway link plus the `config_entries` deprecation fix
  (#160) and the nlbwmon registry fix (#164). Prod runs plain HACS v2.5.3 (installed
  2026-10-11, files md5-identical to the tag; passed the real-HA setup check on 2026.10.0).
  No file swap is needed until a new fix branch exists. The v2.5.2-based build is kept as the local
  branch `all-changes-v2.5.2`.
- Upstream's red "Lint & Test" since HA 2026.10.0 was its `probatio` typing in
  `config_flow.py`, `repairs.py`, `services.py`; upstream `88bc38a` addresses mypy errors.
- A shutdown that lands mid-poll logs `Unexpected error fetching ... data` /
  `RuntimeError: Executor shutdown has been called` from the tracker-history save in
  `coordinator/tracking.py`. Cosmetic, upstream, not ours.
- Inferred, untested: the TX-power cleanup in `number.py` removes every TX-power slider if a
  router reports no wireless interfaces at setup.
- The real-HA harness lives only in a scratchpad and has to be recreated each time;
  committing it to the fork would make the pre-deploy check cheap.
