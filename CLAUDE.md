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

- Prod: HACS v2.5.1 with `all-changes` = v2.5.1 + `fix/tracker-stale-device-cleanup` +
  `fix/luci-rpc-reauth-storm` swapped on top. Both fixes cherry-pick onto v2.5.1 without
  conflicts, and the build loads with no errors on real HA at prod's version.
- stale-device cleanup: merged upstream as FaserF/ha-openwrt#156 on 2026-10-05 (merge
  commit `b1c1ade`, all three commits), not yet in a release. `all-changes` still carries
  it as three cherry-picks; at the first rebuild on a release that contains `b1c1ade`, drop
  them. Code: `OpenWrtDataCoordinator._async_update_device_registry` and
  `async_remove_config_entry_device` in `__init__.py`; tests in
  `tests/test_untracked_device_cleanup.py`.
- LuCI reauth has no PR yet, on purpose: it goes upstream only after it has handled a real
  token expiry in production. `_rpc_call` in `api/luci_rpc/client.py` (one re-login per
  expired token under a lock); tests at the end of `tests/test_api_luci_rpc.py`. Its branch,
  `fix/luci-rpc-reauth-storm`, is local only and based on an older `upstream/main`
  (`50ae700`): rebase it onto current `upstream/main` before a PR.
- v2.5.1 logs HA's "devices used as a mapping" deprecation on 2026.9+ (a
  `hasattr(registry.devices, "values")` probe in `coordinator.py`); upstream removed it on
  `main` in `1f4af94` (#152), so it goes away with the next release.
- Inferred, untested: the TX-power cleanup in `number.py` removes every TX-power slider if a
  router reports no wireless interfaces at setup.
- The real-HA harness lives only in a scratchpad and has to be recreated each time;
  committing it to the fork would make the pre-deploy check cheap.
