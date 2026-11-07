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
  unmerged fix branches (cherry-picked or merged) + this file's commit. Never base it on
  `upstream/main`: unreleased main crashed every router on HA 2026.9 on 2026-09-28.
- `deploy/firmware-fixes`: the 2026-10-20 firmware build (v2.5.3 tag + twelve commits),
  deployed from its own branch and merged into `all-changes` on 2026-10-24. Superseded:
  never deploy from it.
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

- **Prod runs plain upstream v2.5.4, not this branch** (hash-checked 2026-11-07: all 94 files
  match the v2.5.4 tag, the manifest only by `2.5.4` vs `2.5.4-dev0`). The HACS update was
  written 2026-11-05 00:40 and loaded at that day's Core 2026.11 start; nothing records who
  ran it. It dropped the twelve fork commits below, so the HA update button on a router now
  takes upstream's install path (stock image, `sysupgrade -F` for custom builds). v2.5.5
  (2026-11-07) is pending and still has both problems. `all-changes` is NOT a deploy
  candidate until it is rebuilt on the current release.
- The twelve are upstream PRs since 2026-11-07, rebased onto `upstream/main` @ `50ed8b1`
  (after upstream's API module split; every moved function is identical to the tested
  version): FaserF/ha-openwrt#215 `fix/firmware-asu` (ASU detection, package list, client
  id, plus a pure-move refactor into `coordinator/firmware_asu.py` and
  `update_release_notes.py` to stay under upstream's 600-line limit), #216
  `fix/firmware-install-safety` (stacked on #215: sha256 checks, image selection, detached
  installs; helpers in a new `api/firmware_install.py`), #217
  `fix/firmware-entity-freshness`, #218 `fix/backup-download` (fixes upstream issue #212;
  replaces #212's three-step LuCI download). The old local `pr/*`, `pr-main/*` and
  per-fix `fix/*` branches are superseded by these four. Whichever of #215-#218 merges
  second needs a rebase: they append to the same test files and insert next to each other
  in `api/client/helpers.py`.
- Hassfest fails on every PR against `upstream/main` since 2026-11-07: upstream's own
  `manifest.json` puts `quality_scale` after `version` ("keys are not sorted"). Not ours.
- Corrected 2026-11-07: luci-mod-rpc has no `file` (or `ubus`) namespace, only auth, uci,
  fs, sys, ipkg and ip (read on routers, 26.288). The old backup commit's claim that its
  `file.read` "returns the raw content" was wrong; the call 404s.
- `all-changes`: v2.5.3 + `deploy/firmware-fixes` (merged 2026-10-24) + this file. The
  merge added 12 commits: ten firmware fixes (ASU detection and requests, image
  verification, detached installs, version tracking, check timing), one backup-download fix
  and one test. v2.5.3 (2026-10-11) carries every earlier fork fix: LuCI reauth
  (FaserF/ha-openwrt#159), the gateway link plus the `config_entries` deprecation fix (#160)
  and the nlbwmon registry fix (#164). The v2.5.2-based build is kept as the local branch
  `all-changes-v2.5.2`.
- History: prod ran this branch's integration code (HACS v2.5.3 with the twelve swapped over
  it from `deploy/firmware-fixes` @ `629a553`) from the 2026-10-20 restart until the
  2026-11-05 HACS update.
- FaserF/ha-openwrt#195 (branch `fix/action-forces-slow-poll`, from `upstream/main`
  2026-10-23) merged upstream 2026-10-24 (`7889f9c`), released in v2.5.4 and live on prod
  since 2026-11-05. Every router action reset the never-read `_last_full_poll`, so the
  refresh after a service-switch toggle did not re-read services (slow tier, 900 s).
  Actions now call `_invalidate_slow_poll()`, with a generation counter so one landing
  mid-poll is not overwritten (race found by CodeRabbit). FaserF's review bot asked for
  file splits and logging in pre-existing code; upstream did the file split itself on
  2026-11-07 (`60a36da`, a 600-line limit).
- Upstream's red "Lint & Test" since HA 2026.10.0 was its `probatio` typing in
  `config_flow.py`, `repairs.py`, `services.py`; upstream `88bc38a` addresses mypy errors.
- A shutdown that lands mid-poll logs `Unexpected error fetching ... data` /
  `RuntimeError: Executor shutdown has been called` from the tracker-history save in
  `coordinator/tracking.py`. Cosmetic, upstream, not ours.
- Inferred, untested: the TX-power cleanup in `number.py` removes every TX-power slider if a
  router reports no wireless interfaces at setup.
- The real-HA harness lives only in a scratchpad and has to be recreated each time;
  committing it to the fork would make the pre-deploy check cheap.
