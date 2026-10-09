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

- `all-changes`: v2.5.2 + `fix/luci-rpc-reauth-storm` (2 commits) + `fix/gateway-via-device`
  + the docs commits. Passed the real-HA check on HA 2026.9.4; plain v2.5.2 failed it
  (router left unlinked from its gateway).
- stale-device cleanup (#156) shipped in v2.5.2; the cherry-picks are gone from
  `all-changes`.
- LuCI reauth: upstream PR FaserF/ha-openwrt#159, open. `_rpc_call` in
  `api/luci_rpc/client.py` (one re-login per expired token under a lock); tests at the end
  of `tests/test_api_luci_rpc.py`. A forced rpcd restart on a router left 8 rpcd sessions
  without it and 1 with it; neither run logged errors.
- Gateway link (`fix/gateway-via-device`, no PR yet): v2.5.2 looks the gateway up with
  `async_get_device_by_connection(conn, entry_id)`, which only searches this entry, so a
  router never links to an upstream router owned by another entry. The fix searches every
  entry with `async_get_devices(connections=...)` and skips this entry's own devices.
  Deployed 2026-10-06; Routers 2-5 link to Router1 on prod. Held on prod through
  2026-10-09 (15 HA restarts, no openwrt errors beyond known noise), then opened upstream
  as FaserF/ha-openwrt#160: one commit (`9e133a1`) rebased onto `upstream/main` 4ae06c9,
  pushed to `origin/fix/gateway-via-device`. Tests: `tests/test_gateway_via_device.py`.
- HA's "`device_registry.devices` used as a mapping" deprecation still logs once per
  startup from `coordinator/features.py` (the `hasattr(device_reg.devices, "values")`
  probe, ~line 181); #152 only removed the copy in the old `coordinator.py`. Still on
  `upstream/main`. Agreed: a separate small upstream PR, now that the gateway one is open.
- A shutdown that lands mid-poll logs `Unexpected error fetching ... data` /
  `RuntimeError: Executor shutdown has been called` from the tracker-history save in
  `coordinator/tracking.py`. Cosmetic, upstream, not ours.
- Inferred, untested: the TX-power cleanup in `number.py` removes every TX-power slider if a
  router reports no wireless interfaces at setup.
- The real-HA harness lives only in a scratchpad and has to be recreated each time;
  committing it to the fork would make the pre-deploy check cheap.
