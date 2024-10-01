import subprocess


def test_snap_installed():
    subprocess.check_call(["snap", "list", "smartctl-exporter"])
