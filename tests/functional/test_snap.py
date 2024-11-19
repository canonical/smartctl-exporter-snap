import json
import subprocess
import urllib.request
from contextlib import contextmanager

from tenacity import Retrying, retry, stop_after_delay, wait_fixed

ENDPOINT = "http://localhost:9633/metrics"
SYSTEMD_SERVICE = "snap.smartctl-exporter.smartctl-exporter"
SNAP_NAME = "smartctl-exporter"


@retry(wait=wait_fixed(2), stop=stop_after_delay(10))
def _assert_service_failed() -> None:
    """Assert the systemd service is in a failed state."""
    assert 0 == subprocess.call(
        f"sudo systemctl is-failed --quiet {SYSTEMD_SERVICE}".split()
    ), f"{SYSTEMD_SERVICE} is running"


@retry(wait=wait_fixed(2), stop=stop_after_delay(10))
def _assert_service_active() -> None:
    """Assert the systemd service is in a active state."""
    assert 0 == subprocess.call(
        f"sudo systemctl is-active --quiet {SYSTEMD_SERVICE}".split()
    ), f"{SYSTEMD_SERVICE} is not running"


@retry(wait=wait_fixed(5), stop=stop_after_delay(30))
def _assert_endpoint_reachable(endpoint: str) -> None:
    """Assert the endpoint is reachable."""
    response = urllib.request.urlopen(endpoint)  # will raise if not reachable
    status_code = response.getcode()
    assert status_code == 200, f"Endpoint {endpoint} returned status code {status_code}"


@retry(wait=wait_fixed(5), stop=stop_after_delay(30))
def _get_endpoint_data(endpoint: str) -> str:
    """Get the data from an endpoint."""
    response = urllib.request.urlopen(endpoint)
    return response.read().decode("utf-8")


@retry(wait=wait_fixed(2), stop=stop_after_delay(10))
def _assert_service_listening(bind: str, service: str) -> None:
    """Assert service is listening on a specific bind."""
    pid = subprocess.check_output(f"sudo lsof -t -i {bind}".split(), text=True).strip()
    assert service in subprocess.check_output(
        f"cat /proc/{pid}/cmdline".split(), text=True
    ), f"{service} is not listening on {bind}"


@retry(wait=wait_fixed(2), stop=stop_after_delay(10))
def _set_snap_config(config_parent: str, config: str, value: str) -> None:
    """Set a configuration value for a snap service."""
    assert 0 == subprocess.call(
        f"sudo snap set {SNAP_NAME} {config_parent}.{config}={value}".split()
    ), f"Failed to set {config_parent}.{config} to {value}"


@retry(wait=wait_fixed(2), stop=stop_after_delay(10))
def _unset_snap_config(config_parent: str, config: str) -> None:
    """Unset a configuration value for a snap service."""
    assert 0 == subprocess.call(
        f"sudo snap unset {SNAP_NAME} {config_parent}.{config}".split()
    ), f"Failed to unset {config}"


def _get_start_cmd(process: str) -> str:
    """Get the command used to start a process."""
    return subprocess.check_output(f"ps -C {process} -o cmd -ww".split(), text=True)


def _assert_config_exists(config_parent: str, config: str):
    """Check if a configuration exists in the snap configuration."""
    result = subprocess.check_output(f"sudo snap get {SNAP_NAME} -d".split(), text=True)
    smartctl_snap_config = json.loads(result.strip())
    assert (
        config in smartctl_snap_config[config_parent]
    ), f"{config} is not in the snap configuration"


@contextmanager
def _snap_config_ctx(config_str, new_value):
    """Set up a context manager to test snap configuration."""
    config_parent, config = config_str.split(".")
    try:
        _assert_config_exists(config_parent, config)
        _set_snap_config(config_parent, config, new_value)
        yield
    finally:
        # Revert back
        _unset_snap_config(config_parent, config)
        _assert_service_active()


# Snap tests


def test_smartctl_exporter_service() -> None:
    """Test of the smartctl_exporter service and its endpoint."""
    _assert_service_active()
    _assert_endpoint_reachable(ENDPOINT)


def test_smartctl_exporter_metrics() -> None:
    """Test the metrics of the smartctl_exporter service."""
    data = _get_endpoint_data(ENDPOINT)
    assert "smartctl_devices" in data


def test_valid_bind_config() -> None:
    """Test valid snap bind configuration."""
    new_bind = ":9770"
    with _snap_config_ctx("web.listen-address", new_bind):
        _assert_service_listening(new_bind, "smartctl_exporter")


def test_invalid_bind_config() -> None:
    """Test invalid snap bind configuration."""
    with _snap_config_ctx("web.listen-address", "test"):
        _assert_service_failed()


def test_valid_log_level_config() -> None:
    """Test valid snap log level configuration."""
    with _snap_config_ctx("log.level", "debug"):
        _assert_service_active()
        for attempt in Retrying(wait=wait_fixed(2), stop=stop_after_delay(10)):
            with attempt:
                assert "log.level=debug" in _get_start_cmd(
                    "smartctl_exporter"
                ), "log.level=debug was not set"


def test_invalid_log_level_config() -> None:
    """Test invalid snap log level configuration."""
    with _snap_config_ctx("log.level", "test"):
        _assert_service_failed()


def test_include_device_config() -> None:
    """Test include device configuration."""
    with _snap_config_ctx("smartctl.device-include", "/dev/test"):
        _assert_service_active()
        # By giving an invalid device, the exporter should not scan any devices
        assert "smartctl_devices 0" in _get_endpoint_data(ENDPOINT)


def test_exclude_device_config() -> None:
    """Test exclude device configuration."""
    # Take the first device from lsblk and try to exclude it
    result = subprocess.check_output("sudo lsblk -d -e7 -J".split(), text=True)
    device_name = json.loads(result)["blockdevices"][0]["name"]

    with _snap_config_ctx("smartctl.device-exclude", device_name):
        _assert_service_active()
        assert device_name not in _get_endpoint_data(ENDPOINT)
