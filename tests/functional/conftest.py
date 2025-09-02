import subprocess

import pytest


@pytest.fixture(scope="session", autouse=True)
def install_dcgm_snap():
    """Install the snap for testing."""
    subprocess.check_call(
        "sudo snap install --dangerous smartctl-exporter_*.snap",
        shell=True,
    )

    # Manually connect the interface as auto-connect is not allowed in dangerous mode
    subprocess.check_call(["sudo", "snap", "connect", "smartctl-exporter:block-devices"])
    subprocess.check_call(["sudo", "snap", "connect", "smartctl-exporter:hardware-observe"])
    subprocess.check_call(["sudo", "snap", "connect", "smartctl-exporter:network-observe"])

    # Restart the service to apply the interface connection (fails without it)
    subprocess.check_call(["sudo", "snap", "restart", "smartctl-exporter"])

    yield

    subprocess.check_call(["sudo", "snap", "remove", "--purge", "smartctl-exporter"])
