"""Tests for firmware update backup failure and URL resolution."""

from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from custom_components.openwrt.api import base
from custom_components.openwrt.api.base import (
    FIRMWARE_FLASHING,
    FIRMWARE_JOB_BUSY,
    FIRMWARE_JOB_CANCELLED,
    FIRMWARE_JOB_EXIT,
    FIRMWARE_JOB_MISSING,
    FIRMWARE_JOB_RUNNING,
    FIRMWARE_JOB_STARTED,
    FIRMWARE_JOB_TOO_LATE,
)
from custom_components.openwrt.coordinator import OpenWrtData, OpenWrtDataCoordinator
from custom_components.openwrt.update import OpenWrtUpdateEntity


class _FakeJobRouter:
    """Answer the detached install's commands the way the router's shell would.

    polls are returned one per poll (an Exception is raised instead), the last
    one repeating; after a cancel, the polls in after_cancel take over. A poll answer that does not end the job gets the running
    marker appended, as the poll command prints it for a live job.
    """

    def __init__(
        self,
        polls: list,
        launch: object = FIRMWARE_JOB_STARTED,
        cancel: object = FIRMWARE_JOB_CANCELLED,
        after_cancel: list | None = None,
    ) -> None:
        self.polls = list(polls)
        self.after_cancel = after_cancel
        self.launch = launch
        self.cancel = cancel
        self.launches: list[str] = []
        self.cancels = 0
        self.poll_count = 0

    async def __call__(self, command: str) -> str:
        if "sysupgrade" in command:
            self.launches.append(command)
            answer = self.launch
        elif FIRMWARE_JOB_TOO_LATE in command:
            self.cancels += 1
            answer = self.cancel
        else:
            self.poll_count += 1
            if self.cancels and self.after_cancel is not None:
                self.polls, self.after_cancel = self.after_cancel, None
            answer = self.polls.pop(0) if len(self.polls) > 1 else self.polls[0]
            if isinstance(answer, str) and FIRMWARE_JOB_EXIT not in answer:
                answer = f"{answer}\n{FIRMWARE_JOB_RUNNING}"
        if isinstance(answer, Exception):
            raise answer
        return answer


@pytest.mark.asyncio
async def test_firmware_update_backup_failure_aborts(hass: HomeAssistant) -> None:
    """Test that a backup failure during firmware update raises HomeAssistantError and aborts."""
    entry = MagicMock()
    entry.entry_id = "test_entry_id"
    entry.options = {"auto_backup": True, "update_interval": 30}
    entry.data = {"host": "192.168.1.1"}

    mock_client = AsyncMock()
    # Mock create_backup returning None (failure)
    mock_client.create_backup.return_value = None

    coordinator = MagicMock(spec=OpenWrtDataCoordinator)
    coordinator.hass = hass
    coordinator.config_entry = entry
    coordinator.client = mock_client
    coordinator.router_id = "11:22:33:44:55:66"
    coordinator.data = OpenWrtData()
    coordinator.data.firmware_install_url = "http://example.com/firmware.bin"

    update_entity = OpenWrtUpdateEntity(coordinator, entry)
    update_entity.hass = hass

    with pytest.raises(HomeAssistantError, match="Failed to create backup on router"):
        await update_entity.async_install(
            version="25.12.5", backup=True, keep_settings=True
        )


@pytest.mark.asyncio
async def test_async_set_stable_release_urls(hass: HomeAssistant) -> None:
    """Test that _async_set_stable_release_urls dynamically fetches profiles.json."""
    entry = MagicMock()
    entry.entry_id = "test_entry_id"
    entry.options = {"update_interval": 30}
    entry.data = {"host": "192.168.1.1"}

    mock_client = AsyncMock()
    coordinator = OpenWrtDataCoordinator(hass, entry, mock_client)

    data = OpenWrtData()
    data.device_info.target = "mediatek/filogic"
    data.device_info.board_name = "xiaomi_mi-router-ax3000t-ubootmod"
    data.device_info.release_distribution = "openwrt"

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(
        return_value={
            "profiles": {
                "xiaomi-mi-router-ax3000t-ubootmod": {
                    "images": [
                        {
                            "name": "openwrt-25.12.5-mediatek-filogic-xiaomi_mi-router-ax3000t-ubootmod-squashfs-sysupgrade.itb",
                            "type": "sysupgrade",
                        }
                    ]
                }
            }
        }
    )

    mock_session = MagicMock(spec=aiohttp.ClientSession)
    mock_session.get.return_value.__aenter__.return_value = mock_resp

    await coordinator._async_set_stable_release_urls(data, "25.12.5", mock_session)

    # Assert dynamic URL resolved from profiles.json
    assert (
        data.firmware_install_url
        == "https://downloads.openwrt.org/releases/25.12.5/targets/mediatek/filogic/openwrt-25.12.5-mediatek-filogic-xiaomi_mi-router-ax3000t-ubootmod-squashfs-sysupgrade.itb"
    )


@pytest.mark.asyncio
async def test_check_snapshot_update_release_branch(hass: HomeAssistant) -> None:
    """Test that _check_snapshot_update correctly targets release branch snapshots."""
    entry = MagicMock()
    entry.entry_id = "test_entry_id"
    entry.options = {"update_interval": 30}
    entry.data = {"host": "192.168.1.1"}

    mock_client = AsyncMock()
    coordinator = OpenWrtDataCoordinator(hass, entry, mock_client)

    data = OpenWrtData()
    data.device_info.target = "x86/64"
    data.device_info.board_name = "qemu-standard-pc-q35-ich9-2009"
    data.device_info.release_version = "25.12-SNAPSHOT"
    data.firmware_current_version = "25.12-SNAPSHOT (r33058-949e61ec65)"

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(
        return_value={
            "version_code": "r35287-b519bc3b76",
            "profiles": {
                "qemu_standard_pc_q35_ich9_2009": {
                    "images": [
                        {
                            "name": "openwrt-25.12-SNAPSHOT-x86-64-generic-ext4-combined.img.gz",
                            "type": "combined",
                        },
                        {
                            "name": "openwrt-25.12-SNAPSHOT-x86-64-generic-squashfs-sysupgrade.img.gz",
                            "type": "sysupgrade",
                        },
                    ]
                }
            },
        }
    )

    mock_session = MagicMock(spec=aiohttp.ClientSession)
    mock_session.get.return_value.__aenter__.return_value = mock_resp

    await coordinator._check_snapshot_update(data, mock_session)

    assert data.firmware_latest_version == "25.12-SNAPSHOT (r35287-b519bc3b76)"
    assert data.firmware_upgradable is True
    assert (
        data.firmware_release_url
        == "https://downloads.openwrt.org/releases/25.12-SNAPSHOT/targets/x86/64/"
    )
    assert (
        data.firmware_install_url
        == "https://downloads.openwrt.org/releases/25.12-SNAPSHOT/targets/x86/64/openwrt-25.12-SNAPSHOT-x86-64-generic-squashfs-sysupgrade.img.gz"
    )


@pytest.mark.asyncio
async def test_sysupgrade_command_has_no_trailing_rm() -> None:
    """Test that install_firmware does not append a trailing 'rm -f /tmp/firmware.bin'."""
    from custom_components.openwrt.api.luci_rpc import LuciRpcClient
    from custom_components.openwrt.api.ssh import SshClient
    from custom_components.openwrt.api.ubus import UbusClient

    ubus_client = UbusClient(
        MagicMock(), MagicMock(), host="192.168.1.1", username="root", password="pwd"
    )
    luci_client = LuciRpcClient(
        MagicMock(), MagicMock(), host="192.168.1.1", username="root", password="pwd"
    )
    ssh_client = SshClient(
        MagicMock(), MagicMock(), host="192.168.1.1", username="root", password="pwd"
    )

    for client in (ubus_client, luci_client):
        router = _FakeJobRouter([f"{FIRMWARE_FLASHING}\n{FIRMWARE_JOB_EXIT}0"])
        with (
            patch.object(client, "_firmware_exec", router),
            patch.object(base, "FIRMWARE_POLL_INTERVAL", 0),
        ):
            await client.install_firmware(
                "http://example.com/firmware.bin", keep_settings=True, force=False
            )
        (cmd,) = router.launches
        assert "sysupgrade" in cmd
        assert "rm -f /tmp/firmware.bin )" not in cmd

    with patch.object(ssh_client, "_exec", new_callable=AsyncMock) as mock_exec:
        await ssh_client.install_firmware(
            "http://example.com/firmware.bin", keep_settings=True, force=False
        )
        cmd = mock_exec.call_args[0][0]
        assert "sysupgrade" in cmd
        assert not cmd.endswith("rm -f /tmp/firmware.bin")


# --- Verified firmware download ---

SHA = "ab" * 32


def test_sysupgrade_command_verifies_checksum_and_tls() -> None:
    """The command checks TLS and the checksum, and never forces sysupgrade."""
    from custom_components.openwrt.api.base import (
        FIRMWARE_CHECKSUM_MISMATCH,
        build_sysupgrade_command,
    )

    cmd = build_sysupgrade_command(
        "https://example.com/fw.bin", keep_settings=True, sha256=SHA.upper()
    )
    assert "--no-check-certificate" not in cmd
    assert "curl -k" not in cmd
    assert "sysupgrade -F" not in cmd
    assert f'= "{SHA}" ]' in cmd
    assert cmd.index("sha256sum") < cmd.index("sysupgrade /tmp/firmware.bin")
    assert FIRMWARE_CHECKSUM_MISMATCH in cmd
    assert cmd.endswith("sysupgrade /tmp/firmware.bin")

    no_sum = build_sysupgrade_command("https://example.com/fw.bin")
    assert "sha256sum" not in no_sum
    assert build_sysupgrade_command("u", keep_settings=False).endswith(
        "sysupgrade -n /tmp/firmware.bin"
    )


def test_sysupgrade_command_rejects_malformed_checksum() -> None:
    """A checksum that is not 64 hex digits never reaches the shell."""
    from custom_components.openwrt.api.base import (
        FirmwareInstallError,
        build_sysupgrade_command,
    )

    with pytest.raises(FirmwareInstallError):
        build_sysupgrade_command("u", sha256='"; reboot; echo "')


@pytest.mark.asyncio
async def test_install_firmware_raises_on_checksum_mismatch() -> None:
    """Each client turns the router's mismatch marker into an error."""
    from custom_components.openwrt.api.base import (
        FIRMWARE_CHECKSUM_MISMATCH,
        FirmwareInstallError,
    )
    from custom_components.openwrt.api.luci_rpc import LuciRpcClient
    from custom_components.openwrt.api.ssh import SshClient
    from custom_components.openwrt.api.ubus import UbusClient

    kwargs = {"host": "192.0.2.1", "username": "root", "password": "pwd"}
    for client in (
        UbusClient(MagicMock(), MagicMock(), **kwargs),
        LuciRpcClient(MagicMock(), MagicMock(), **kwargs),
    ):
        router = _FakeJobRouter([f"{FIRMWARE_CHECKSUM_MISMATCH}\n{FIRMWARE_JOB_EXIT}1"])
        with (
            patch.object(client, "_firmware_exec", router),
            patch.object(base, "FIRMWARE_POLL_INTERVAL", 0),
            pytest.raises(FirmwareInstallError, match="checksum mismatch"),
        ):
            await client.install_firmware("https://example.com/fw.bin", sha256=SHA)
        assert "sha256sum" in router.launches[0]

    ssh = SshClient(MagicMock(), MagicMock(), **kwargs)
    with patch.object(ssh, "_exec", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = f"{FIRMWARE_CHECKSUM_MISMATCH}\n"
        with pytest.raises(FirmwareInstallError, match="checksum mismatch"):
            await ssh.install_firmware("https://example.com/fw.bin", sha256=SHA)
        assert "sha256sum" in mock_exec.call_args[0][0]


@pytest.mark.asyncio
async def test_custom_build_install_passes_checksum_without_force(
    hass: HomeAssistant,
) -> None:
    """Custom repository images are verified and not flashed with -F."""
    entry = MagicMock()
    entry.entry_id = "test_entry_id"
    entry.options = {"auto_backup": False}
    entry.data = {"host": "192.0.2.1"}

    coordinator = MagicMock(spec=OpenWrtDataCoordinator)
    coordinator.hass = hass
    coordinator.config_entry = entry
    coordinator.client = AsyncMock()
    coordinator.router_id = "00:00:5e:00:53:01"
    coordinator.data = OpenWrtData()
    coordinator.data.is_custom_build = True
    coordinator.data.firmware_install_url = "https://example.com/fw-sysupgrade.bin"
    coordinator.data.firmware_checksum = SHA

    entity = OpenWrtUpdateEntity(coordinator, entry)
    entity.hass = hass
    await entity.async_install(version=None, backup=False)

    coordinator.client.install_firmware.assert_awaited_once_with(
        "https://example.com/fw-sysupgrade.bin",
        keep_settings=True,
        force=False,
        sha256=SHA,
    )


@pytest.mark.asyncio
async def test_custom_checksum_matches_exact_file_name(hass: HomeAssistant) -> None:
    """The checksum is taken from the line for exactly this file name."""
    entry = MagicMock()
    entry.entry_id = "test_entry_id"
    entry.options = {"update_interval": 30}
    entry.data = {"host": "192.0.2.1"}
    coordinator = OpenWrtDataCoordinator(hass, entry, AsyncMock())

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.text = AsyncMock(
        return_value=(
            f"{'11' * 32}  fw-sysupgrade.bin.sig\n"
            f"{'22' * 32}  other-fw-sysupgrade.bin\n"
            f"{'33' * 32} *fw-sysupgrade.bin\n"
        )
    )
    mock_session = MagicMock(spec=aiohttp.ClientSession)
    mock_session.get.return_value.__aenter__.return_value = mock_resp

    data = OpenWrtData()
    await coordinator._fetch_custom_checksum(
        data, "https://example.com/sha256sums", "fw-sysupgrade.bin", mock_session
    )
    assert data.firmware_checksum == "33" * 32


# --- ASU image selection and checksum ---


def _asu_done(images: list[dict]) -> dict:
    """An ASU GET /api/v1/build/{hash} response for a finished build."""
    return {"status": 200, "detail": "done", "bin_dir": "f00d", "images": images}


@pytest.mark.asyncio
async def test_asu_poll_returns_sysupgrade_image_and_sha256(
    hass: HomeAssistant,
) -> None:
    """The sysupgrade image is picked by type, never the first image."""
    from custom_components.openwrt.helpers.asu import AsuClient

    client = AsuClient(hass, "https://asu.example.com/")
    images = [
        {"name": "fw-initramfs-kernel.bin", "type": "kernel", "sha256": "11" * 32},
        {"name": "fw-squashfs-factory.bin", "type": "factory", "sha256": "22" * 32},
        {
            "name": "fw-squashfs-sysupgrade.bin",
            "type": "sysupgrade",
            "filesystem": "squashfs",
            "sha256": SHA,
        },
    ]
    with patch.object(client, "_request", AsyncMock(return_value=_asu_done(images))):
        image = await client.poll_build_status("f00d")

    assert image.url == "https://asu.example.com/store/f00d/fw-squashfs-sysupgrade.bin"
    assert image.sha256 == SHA


@pytest.mark.asyncio
async def test_asu_poll_prefers_squashfs_sysupgrade(hass: HomeAssistant) -> None:
    """With several sysupgrade filesystems, squashfs wins."""
    from custom_components.openwrt.helpers.asu import AsuClient

    client = AsuClient(hass)
    images = [
        {
            "name": "fw-ext4-sysupgrade.img.gz",
            "type": "sysupgrade",
            "filesystem": "ext4",
            "sha256": "33" * 32,
        },
        {
            "name": "fw-squashfs-sysupgrade.img.gz",
            "type": "sysupgrade",
            "filesystem": "squashfs",
            "sha256": SHA,
        },
    ]
    with patch.object(client, "_request", AsyncMock(return_value=_asu_done(images))):
        image = await client.poll_build_status("f00d")
    assert image.url.endswith("fw-squashfs-sysupgrade.img.gz")
    assert image.sha256 == SHA


@pytest.mark.parametrize(
    "images",
    [
        # Only a factory image (previously flashed as the fallback).
        [{"name": "fw-squashfs-factory.bin", "type": "factory", "sha256": SHA}],
        # Combined (x86) images are not sysupgrade images.
        [{"name": "fw-combined-efi.img.gz", "type": "combined-efi", "sha256": SHA}],
        # A sysupgrade image without a usable checksum.
        [{"name": "fw-sysupgrade.bin", "type": "sysupgrade"}],
        [{"name": "fw-sysupgrade.bin", "type": "sysupgrade", "sha256": "abc"}],
        [],
    ],
)
@pytest.mark.asyncio
async def test_asu_poll_refuses_without_verified_sysupgrade_image(
    hass: HomeAssistant, images: list[dict]
) -> None:
    """No sysupgrade image, or no sha256 for it, is an error, not a guess."""
    from custom_components.openwrt.helpers.asu import AsuClient, AsuClientError

    client = AsuClient(hass)
    with (
        patch.object(client, "_request", AsyncMock(return_value=_asu_done(images))),
        pytest.raises(AsuClientError),
    ):
        await client.poll_build_status("f00d")


def _install_entity(hass: HomeAssistant, data: OpenWrtData) -> OpenWrtUpdateEntity:
    entry = MagicMock()
    entry.entry_id = "test_entry_id"
    entry.options = {"auto_backup": False}
    entry.data = {"host": "192.0.2.1", "connection_type": "ssh"}

    coordinator = MagicMock(spec=OpenWrtDataCoordinator)
    coordinator.hass = hass
    coordinator.config_entry = entry
    coordinator.client = AsyncMock()
    coordinator.router_id = "00:00:5e:00:53:01"
    coordinator.name = "router-a"
    coordinator.data = data

    entity = OpenWrtUpdateEntity(coordinator, entry)
    entity.hass = hass
    return entity


@pytest.mark.asyncio
async def test_asu_install_passes_image_sha256(hass: HomeAssistant) -> None:
    """The ASU image is flashed with the checksum the ASU server published."""
    from custom_components.openwrt.helpers.asu import AsuImage

    data = OpenWrtData()
    data.asu_supported = True
    data.asu_update_available = True
    data.firmware_latest_version = "25.12.6"
    entity = _install_entity(hass, data)

    url = "https://asu.example.com/store/f00d/fw-squashfs-sysupgrade.bin"
    with patch("custom_components.openwrt.helpers.asu.AsuClient") as asu_cls:
        asu_cls.return_value.request_build = AsyncMock(return_value="f00d")
        asu_cls.return_value.poll_build_status = AsyncMock(
            return_value=AsuImage(url=url, sha256=SHA)
        )
        await entity.async_install(version=None, backup=False)

    entity.coordinator.client.install_firmware.assert_awaited_once_with(
        url, keep_settings=True, force=False, sha256=SHA
    )


# --- Official (stock) image checksum ---


def _profiles_coordinator(hass: HomeAssistant, profiles_json: dict):
    entry = MagicMock()
    entry.entry_id = "test_entry_id"
    entry.options = {"update_interval": 30}
    entry.data = {"host": "192.0.2.1"}
    coordinator = OpenWrtDataCoordinator(hass, entry, AsyncMock())

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(return_value=profiles_json)
    mock_session = MagicMock(spec=aiohttp.ClientSession)
    mock_session.get.return_value.__aenter__.return_value = mock_resp
    return coordinator, mock_session


@pytest.mark.asyncio
async def test_stable_release_carries_profiles_sha256(hass: HomeAssistant) -> None:
    """The stable image's sha256 comes from profiles.json with its URL."""
    coordinator, session = _profiles_coordinator(
        hass,
        {
            "profiles": {
                "vendor_router-a": {
                    "images": [
                        {
                            "name": "fw-factory.bin",
                            "type": "factory",
                            "sha256": "11" * 32,
                        },
                        {
                            "name": "fw-sysupgrade.bin",
                            "type": "sysupgrade",
                            "sha256": SHA,
                        },
                    ]
                }
            }
        },
    )
    data = OpenWrtData()
    data.device_info.target = "ramips/mt7621"
    data.device_info.board_name = "vendor,router-a"

    await coordinator._async_set_stable_release_urls(data, "25.12.6", session)

    assert data.firmware_install_url.endswith("/fw-sysupgrade.bin")
    assert data.firmware_checksum == SHA


@pytest.mark.asyncio
async def test_stable_release_guessed_url_has_no_checksum(hass: HomeAssistant) -> None:
    """The guessed fallback URL never inherits a checksum from elsewhere."""
    coordinator, session = _profiles_coordinator(hass, {"profiles": {}})
    data = OpenWrtData()
    data.device_info.target = "ramips/mt7621"
    data.device_info.board_name = "vendor,router-a"
    data.firmware_checksum = "44" * 32

    await coordinator._async_set_stable_release_urls(data, "25.12.6", session)

    assert data.firmware_install_url.endswith("-squashfs-sysupgrade.bin")
    assert data.firmware_checksum == ""


@pytest.mark.asyncio
async def test_snapshot_carries_profiles_sha256(hass: HomeAssistant) -> None:
    """The snapshot image's sha256 comes from profiles.json with its URL."""
    coordinator, session = _profiles_coordinator(
        hass,
        {
            "version_code": "r2-bbbb",
            "profiles": {
                "vendor_router_a": {
                    "images": [
                        {
                            "name": "fw-sysupgrade.bin",
                            "type": "sysupgrade",
                            "sha256": SHA,
                        }
                    ]
                }
            },
        },
    )
    data = OpenWrtData()
    data.device_info.target = "ramips/mt7621"
    data.device_info.board_name = "vendor,router-a"
    data.device_info.release_version = "SNAPSHOT"
    data.firmware_current_version = "SNAPSHOT (r1-aaaa)"

    await coordinator._check_snapshot_update(data, session)

    assert data.firmware_install_url.endswith("/fw-sysupgrade.bin")
    assert data.firmware_checksum == SHA


@pytest.mark.asyncio
async def test_stock_install_passes_checksum(hass: HomeAssistant) -> None:
    """An official image is flashed with its profiles.json checksum."""
    data = OpenWrtData()
    data.firmware_install_url = "https://downloads.example.com/fw-sysupgrade.bin"
    data.firmware_checksum = SHA
    entity = _install_entity(hass, data)

    await entity.async_install(version=None, backup=False)

    entity.coordinator.client.install_firmware.assert_awaited_once_with(
        "https://downloads.example.com/fw-sysupgrade.bin",
        keep_settings=True,
        force=False,
        sha256=SHA,
    )


# --- SSH install timeout ---


def _paramiko_stub(calls: list, read_effect: object) -> MagicMock:
    """A paramiko SSHClient whose stdout.read() has the given side effect."""
    client = MagicMock()

    def exec_command(command: str, timeout: float | None = None):
        calls.append(timeout)
        stdout = MagicMock()
        stdout.read.side_effect = read_effect
        return MagicMock(), stdout, MagicMock()

    client.exec_command.side_effect = exec_command
    return client


@pytest.mark.asyncio
async def test_ssh_install_timeout_is_an_error_and_never_reruns() -> None:
    """A silent download is reported as unknown, not as a reboot, and runs once."""

    from custom_components.openwrt.api.base import FirmwareInstallError
    from custom_components.openwrt.api.ssh import SshClient
    from custom_components.openwrt.api.ssh.features import FIRMWARE_INSTALL_TIMEOUT

    calls: list = []
    client = SshClient(
        MagicMock(), MagicMock(), host="192.0.2.1", username="root", password="pwd"
    )
    client._client = _paramiko_stub(calls, TimeoutError())
    client.connect = AsyncMock(return_value=True)

    with pytest.raises(FirmwareInstallError, match="unknown whether sysupgrade"):
        await client.install_firmware("https://example.com/fw.bin", sha256=SHA)

    # One run with the long timeout; no reconnect-and-rerun of the flash command.
    assert calls == [FIRMWARE_INSTALL_TIMEOUT]
    client.connect.assert_not_awaited()


@pytest.mark.asyncio
async def test_ssh_install_reconnect_failure_is_not_a_reboot() -> None:
    """If the router cannot be reached before the command runs, nothing flashed."""
    from custom_components.openwrt.api.ssh import SshClient, SshConnectionError

    client = SshClient(
        MagicMock(), MagicMock(), host="192.0.2.1", username="root", password="pwd"
    )
    client._client = None
    client.connect = AsyncMock(
        side_effect=SshConnectionError("SSH connection failed: host unreachable")
    )

    with pytest.raises(SshConnectionError):
        await client.install_firmware("https://example.com/fw.bin", sha256=SHA)


@pytest.mark.asyncio
async def test_ssh_exec_timeout_raises_timeout_error() -> None:
    """Ordinary commands keep the 15 s timeout and surface it as a timeout."""

    from custom_components.openwrt.api.ssh import SshClient, SshTimeoutError

    calls: list = []
    client = SshClient(
        MagicMock(), MagicMock(), host="192.0.2.1", username="root", password="pwd"
    )
    client._client = _paramiko_stub(calls, TimeoutError())

    with pytest.raises(SshTimeoutError):
        await client._exec("uptime", retry=False)
    assert calls == [15]


# --- ubus / LuCI RPC detached install ---


def _rpc_clients() -> list:
    """A ubus and a LuCI RPC client, each with its own connection error."""
    from custom_components.openwrt.api.luci_rpc import LuciRpcClient
    from custom_components.openwrt.api.luci_rpc.exceptions import (
        LuciRpcConnectionError,
    )
    from custom_components.openwrt.api.ubus import UbusClient
    from custom_components.openwrt.api.ubus.exceptions import UbusConnectionError

    kwargs = {"host": "192.0.2.1", "username": "root", "password": "pwd"}
    return [
        (UbusClient(MagicMock(), MagicMock(), **kwargs), UbusConnectionError),
        (LuciRpcClient(MagicMock(), MagicMock(), **kwargs), LuciRpcConnectionError),
    ]


@pytest.fixture
def fast_polls():
    """Poll without waiting."""
    with patch.object(base, "FIRMWARE_POLL_INTERVAL", 0):
        yield


@pytest.mark.asyncio
@pytest.mark.parametrize("index", [0, 1], ids=["ubus", "luci_rpc"])
async def test_rpc_install_survives_long_download(index: int, fast_polls) -> None:
    """A download that outlasts any server timeout is polled, not cut off or re-run."""
    client, conn_error = _rpc_clients()[index]
    router = _FakeJobRouter(
        ["Downloading"] * 50
        + [f"Downloading\nDownload completed\n{FIRMWARE_FLASHING}", conn_error("gone")]
    )
    with patch.object(client, "_firmware_exec", router):
        await client.install_firmware("https://example.com/fw.bin", sha256=SHA)

    assert len(router.launches) == 1
    assert router.poll_count == 52
    assert router.cancels == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("index", [0, 1], ids=["ubus", "luci_rpc"])
async def test_rpc_install_timeout_cancels_and_raises(index: int, fast_polls) -> None:
    """A download still running at the deadline is cancelled and reported."""
    client, _ = _rpc_clients()[index]
    router = _FakeJobRouter(["Downloading"])
    with (
        patch.object(client, "_firmware_exec", router),
        patch.object(base, "FIRMWARE_JOB_TIMEOUT", 0.05),
        pytest.raises(base.FirmwareInstallError, match="sysupgrade will not run"),
    ):
        await client.install_firmware("https://example.com/fw.bin", sha256=SHA)

    assert len(router.launches) == 1
    assert router.cancels == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("index", [0, 1], ids=["ubus", "luci_rpc"])
async def test_rpc_install_lost_contact_before_flash_is_unknown(
    index: int, fast_polls
) -> None:
    """Losing the router before sysupgrade starts is an error, never a reboot."""
    client, conn_error = _rpc_clients()[index]
    router = _FakeJobRouter(
        ["Downloading", conn_error("Cannot connect")],
        cancel=conn_error("Cannot connect"),
    )
    with (
        patch.object(client, "_firmware_exec", router),
        patch.object(base, "FIRMWARE_JOB_TIMEOUT", 0.05),
        pytest.raises(base.FirmwareInstallError, match="unknown whether sysupgrade"),
    ):
        await client.install_firmware("https://example.com/fw.bin", sha256=SHA)
    assert len(router.launches) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("index", [0, 1], ids=["ubus", "luci_rpc"])
async def test_rpc_install_router_restart_before_flash_is_an_error(
    index: int, fast_polls
) -> None:
    """A job that vanished before sysupgrade started is not reported as success."""
    client, conn_error = _rpc_clients()[index]
    router = _FakeJobRouter(["Downloading", conn_error("reset"), FIRMWARE_JOB_MISSING])
    with (
        patch.object(client, "_firmware_exec", router),
        pytest.raises(base.FirmwareInstallError, match="restarted"),
    ):
        await client.install_firmware("https://example.com/fw.bin", sha256=SHA)


@pytest.mark.asyncio
@pytest.mark.parametrize("index", [0, 1], ids=["ubus", "luci_rpc"])
async def test_rpc_install_reports_sysupgrade_refusal(index: int, fast_polls) -> None:
    """sysupgrade rejecting the image surfaces its message and exit code."""
    client, _ = _rpc_clients()[index]
    router = _FakeJobRouter(
        [f"{FIRMWARE_FLASHING}\nImage check failed.\n{FIRMWARE_JOB_EXIT}1"]
    )
    with (
        patch.object(client, "_firmware_exec", router),
        pytest.raises(base.FirmwareInstallError, match="exit code 1.*Image check"),
    ):
        await client.install_firmware("https://example.com/fw.bin", sha256=SHA)


@pytest.mark.asyncio
@pytest.mark.parametrize("index", [0, 1], ids=["ubus", "luci_rpc"])
async def test_rpc_install_refuses_while_another_runs(index: int, fast_polls) -> None:
    """A second install while one is running on the router is refused."""
    client, _ = _rpc_clients()[index]
    router = _FakeJobRouter([], launch=FIRMWARE_JOB_BUSY)
    with (
        patch.object(client, "_firmware_exec", router),
        pytest.raises(base.FirmwareInstallError, match="already|still running"),
    ):
        await client.install_firmware("https://example.com/fw.bin", sha256=SHA)
    assert router.poll_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("index", [0, 1], ids=["ubus", "luci_rpc"])
async def test_rpc_install_too_late_to_cancel_follows_the_flash(
    index: int, fast_polls
) -> None:
    """If sysupgrade passed the gate first, the install watches it to the reboot."""
    client, conn_error = _rpc_clients()[index]
    # Polls show the download until the deadline; then the router goes down.
    router = _FakeJobRouter(
        ["Downloading"],
        cancel=FIRMWARE_JOB_TOO_LATE,
        after_cancel=[f"{FIRMWARE_FLASHING}", conn_error("gone")],
    )
    with (
        patch.object(client, "_firmware_exec", router),
        patch.object(base, "FIRMWARE_JOB_TIMEOUT", 0.05),
    ):
        await client.install_firmware("https://example.com/fw.bin", sha256=SHA)
    assert router.cancels == 1
    assert len(router.launches) == 1


def test_detached_command_is_idempotent_per_job() -> None:
    """The launch creates its job directory atomically before anything runs."""
    cmd = base.build_detached_sysupgrade_command(
        "0123456789abcdef", "https://example.com/fw.bin", sha256=SHA
    )
    job = f"{base.FIRMWARE_JOB_DIR_PREFIX}0123456789abcdef"
    assert cmd.startswith(f"if ! mkdir {job} 2>/dev/null; then")
    # The job takes the cancel gate and announces itself before sysupgrade.
    assert (
        cmd.index(f"mkdir {job}/gate")
        < cmd.index(FIRMWARE_FLASHING)
        < cmd.index("sysupgrade /tmp/firmware.bin")
    )
    assert "</dev/null &" in cmd
    with pytest.raises(base.FirmwareInstallError):
        base.build_detached_sysupgrade_command("x; reboot", "u")


@pytest.mark.asyncio
async def test_ubus_rpcd_timeout_is_not_success() -> None:
    """rpcd's exec timeout (status 7) used to read as an empty, successful run."""
    client, _ = _rpc_clients()[0]
    with (
        patch.object(
            client,
            "_call",
            AsyncMock(side_effect=base_ubus_error("Ubus call failed with code 7")),
        ) as call,
        pytest.raises(base.FirmwareInstallError, match="Could not start"),
    ):
        await client.install_firmware("https://example.com/fw.bin", sha256=SHA)
    call.assert_awaited_once()
    # execute_command still swallows it, which is why the install no longer uses it.
    with patch.object(
        client,
        "_call",
        AsyncMock(side_effect=base_ubus_error("Ubus call failed with code 7")),
    ):
        assert await client.execute_command("true") == ""


def base_ubus_error(message: str) -> Exception:
    """A UbusError as _call raises it."""
    from custom_components.openwrt.api.ubus.exceptions import UbusError

    return UbusError(message)


@pytest.mark.asyncio
async def test_luci_bad_gateway_is_not_success_and_not_rerun() -> None:
    """uhttpd's 502 after script_timeout used to fall through to success."""
    from custom_components.openwrt.api.luci_rpc.exceptions import LuciRpcError

    client, _ = _rpc_clients()[1]
    rpc = AsyncMock(
        side_effect=LuciRpcError("Communication error: 502, message='Bad Gateway'")
    )
    with (
        patch.object(client, "_rpc_call", rpc),
        pytest.raises(base.FirmwareInstallError, match="Could not start"),
    ):
        await client.install_firmware("https://example.com/fw.bin", sha256=SHA)
    # One sys.exec, no file.exec fallback that would run the command again.
    rpc.assert_awaited_once()
    endpoint, method, (wrapped,) = rpc.call_args[0]
    assert (endpoint, method) == ("sys", "exec")
    assert wrapped.startswith("/bin/sh -c 'if ! mkdir ")
    assert wrapped.endswith("' 2>&1")
