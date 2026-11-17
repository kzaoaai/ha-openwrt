@AGENTS.MD

# Fork notes (kzaoaai/ha-openwrt)

This file exists only on the fork's `all-changes` branch. Never let it reach a branch meant
for an upstream PR.

## What this is

The owner's fork of `FaserF/ha-openwrt`, the HACS integration for OpenWrt routers.
Remotes: `origin` = the fork, `upstream` = FaserF (PRs target it). Since v2.5.6 every
fork fix is upstream, so `all-changes` carries no code of its own: prod can run the plain
HACS release.

## Branches

- `all-changes`: the latest upstream release tag + the owner's unmerged fix branches
  (cherry-picked or merged) + this file's commit. Today: `v2.5.6` + this file only (rebuilt
  2026-11-17). Never base it on `upstream/main`: unreleased main crashed every router on
  HA 2026.9 on 2026-09-28.
- `all-changes-v2.5.3` (also on `origin`): the previous build, v2.5.3 + the twelve firmware
  and backup commits. `all-changes-v2.5.2` (local): the one before. Rollback reference only.
- `fix/*`: one per upstream PR candidate, cut from freshly fetched `upstream/main`, deleted
  once released. None exists today (all were merged and deleted 2026-11-17).
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

While `all-changes` equals a release (as now), deploying is just the HACS update.
When it carries unmerged fixes: HACS cannot install a fork branch under the upstream entry, so
update the upstream release in HACS first (keeps HACS's record honest), then swap `git archive all-changes
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

- `all-changes` = `v2.5.6` + this file. v2.5.6 (2026-11-17) carries every fork fix:
  FaserF/ha-openwrt#215 (ASU detection and package list), #216 (image verification, detached
  installs), #217 (firmware entity freshness), #218 (backup download, upstream issue #212),
  #226 (restores `get_user_installed_packages()`, which upstream's #218 merge resolution
  dropped; merged as a local branch merge `c154e42`, so GitHub shows #226 closed, not
  merged), plus the earlier #159, #160, #164 and #195. It also fixes upstream issue #219
  (disconnected Wi-Fi clients turning "wired" and staying home), which was why v2.5.5 was
  held.
- Prod runs plain upstream v2.5.6 from HACS (installed and restarted 2026-11-17; all five
  router entries loaded, no openwrt errors in the log). There is no fork code to swap in.
- Upstream's PR checks: Hassfest wants manifest keys sorted (fixed on main by the
  `quality_scale` move in v2.5.6). CodeRabbit runs on its free tier (two reviews per hour);
  after the limit it reviews again only on `@coderabbitai review`. FaserF's bot sometimes
  merges a PR branch locally, which GitHub shows as closed: check `git merge-base
  --is-ancestor <commit> upstream/main` before assuming a PR was rejected.
- luci-mod-rpc has no `file` (or `ubus`) namespace, only auth, uci, fs, sys, ipkg and ip
  (read on routers, 26.288); a `file.read` call 404s.
- A shutdown that lands mid-poll logs `Unexpected error fetching ... data` /
  `RuntimeError: Executor shutdown has been called` from the tracker-history save in
  `coordinator/tracking.py`. Cosmetic, upstream, not ours.
- Inferred, untested: the TX-power cleanup in `number.py` removes every TX-power slider if a
  router reports no wireless interfaces at setup.
- The real-HA harness lives only in a scratchpad and has to be recreated each time;
  committing it to the fork would make the pre-deploy check cheap. From HA 2026.11 it runs on
  HA's own in-tree `pytest_homeassistant` package, not `pytest-homeassistant-custom-component`
  (recipe: memory note `verify-on-real-ha-before-prod`).
