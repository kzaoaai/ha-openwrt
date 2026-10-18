"""Tests for firmware update backup failure and URL resolution."""

from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from custom_components.openwrt.coordinator import OpenWrtData, OpenWrtDataCoordinator
from custom_components.openwrt.update import OpenWrtUpdateEntity


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

    with patch.object(
        ubus_client, "execute_command", new_callable=AsyncMock
    ) as mock_exec:
        await ubus_client.install_firmware(
            "http://example.com/firmware.bin", keep_settings=True, force=False
        )
        cmd = mock_exec.call_args[0][0]
        assert "sysupgrade" in cmd
        assert not cmd.endswith("rm -f /tmp/firmware.bin")

    with patch.object(
        luci_client, "execute_command", new_callable=AsyncMock
    ) as mock_exec:
        await luci_client.install_firmware(
            "http://example.com/firmware.bin", keep_settings=True, force=False
        )
        cmd = mock_exec.call_args[0][0]
        assert "sysupgrade" in cmd
        assert not cmd.endswith("rm -f /tmp/firmware.bin")

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
    clients = [
        (UbusClient(MagicMock(), MagicMock(), **kwargs), "execute_command"),
        (LuciRpcClient(MagicMock(), MagicMock(), **kwargs), "execute_command"),
        (SshClient(MagicMock(), MagicMock(), **kwargs), "_exec"),
    ]
    for client, runner in clients:
        with patch.object(client, runner, new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = f"{FIRMWARE_CHECKSUM_MISMATCH}\n"
            with pytest.raises(FirmwareInstallError, match="checksum mismatch"):
                await client.install_firmware("https://example.com/fw.bin", sha256=SHA)
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
