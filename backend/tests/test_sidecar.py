from pathlib import Path

from kerui_recruit.sidecar import parse_runtime_args


def test_sidecar_accepts_only_explicit_desktop_runtime_values(tmp_path: Path) -> None:
    """Changing argument names or silently choosing a public bind address must break packaging."""
    options = parse_runtime_args([
        "--port", "43127",
        "--token", "a" * 64,
        "--data-root", str(tmp_path / "data"),
    ])

    assert options.host == "127.0.0.1"
    assert options.port == 43127
    assert options.token == "a" * 64
    assert options.data_root == tmp_path / "data"
