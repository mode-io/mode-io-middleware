from __future__ import annotations

import os
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Sequence

from smoke_matrix.common import run_command_capture, write_text


@dataclass
class RuntimeEnvironment:
    mode: str
    setup_command: Sequence[str]
    gateway_command: Sequence[str]
    env: Dict[str, str]
    report: Dict[str, object]


def _venv_bin_dir(venv_root: Path) -> Path:
    return venv_root / ("Scripts" if os.name == "nt" else "bin")


def _command_preview(command: Sequence[str]) -> str:
    return shlex.join(str(part) for part in command)


def _run_checked_command(
    *,
    command: Sequence[str],
    cwd: Path,
    env: Dict[str, str],
    timeout_seconds: int,
    log_path: Path,
) -> Dict[str, object]:
    result = run_command_capture(
        command=command,
        cwd=cwd,
        env=env,
        timeout_seconds=timeout_seconds,
    )
    write_text(
        log_path,
        "\n".join(
            [
                f"$ {_command_preview(command)}",
                "",
                "[stdout]",
                str(result.get("stdout", "")),
                "",
                "[stderr]",
                str(result.get("stderr", "")),
                "",
            ]
        ),
    )
    if int(result.get("exitCode", 1)) != 0:
        raise RuntimeError(
            f"command failed ({result.get('exitCode')}): {_command_preview(command)}"
        )
    return result


def _install_spec_for_mode(
    *,
    mode: str,
    repo_root: Path,
    install_target: str,
    venv_python: Path,
    runtime_dir: Path,
    base_env: Dict[str, str],
    timeout_seconds: int,
    report: Dict[str, object],
) -> str:
    target = install_target.strip()

    if mode == "path":
        resolved = Path(target).expanduser().resolve() if target else repo_root
        report["installSource"] = str(resolved)
        return str(resolved)

    if mode == "git":
        if not target:
            raise RuntimeError("--install-target is required when --install-mode=git")
        report["installSource"] = target
        return target if target.startswith("git+") else f"git+{target}"

    if mode != "wheel":
        raise RuntimeError(f"unsupported install mode: {mode}")

    wheel_dir = runtime_dir / "wheelhouse"
    wheel_dir.mkdir(parents=True, exist_ok=True)

    if target:
        target_path = Path(target).expanduser().resolve()
        if target_path.is_file() and target_path.suffix == ".whl":
            report["installSource"] = str(target_path)
            report["wheelPath"] = str(target_path)
            return str(target_path)
        source_path = target_path
    else:
        source_path = repo_root

    build_command = [
        str(venv_python),
        "-m",
        "pip",
        "wheel",
        "--no-deps",
        "--wheel-dir",
        str(wheel_dir),
        str(source_path),
    ]
    _run_checked_command(
        command=build_command,
        cwd=repo_root,
        env=base_env,
        timeout_seconds=timeout_seconds,
        log_path=runtime_dir / "build-wheel.log",
    )
    wheels = sorted(wheel_dir.glob("*.whl"), key=lambda item: item.stat().st_mtime)
    if not wheels:
        raise RuntimeError("wheel build completed but no wheel was produced")
    wheel_path = wheels[-1]
    report["installSource"] = str(source_path)
    report["wheelPath"] = str(wheel_path)
    return str(wheel_path)


def prepare_runtime(
    *,
    repo_root: Path,
    run_dir: Path,
    timeout_seconds: int,
    install_mode: str,
    install_target: str,
) -> RuntimeEnvironment:
    base_env = dict(os.environ)
    if install_mode == "repo":
        return RuntimeEnvironment(
            mode="repo",
            setup_command=[
                sys.executable,
                str(repo_root / "scripts" / "setup_middleware_gateway.py"),
            ],
            gateway_command=[
                sys.executable,
                str(repo_root / "scripts" / "middleware_gateway.py"),
            ],
            env=base_env,
            report={
                "mode": "repo",
                "installSource": str(repo_root),
                "pythonBin": sys.executable,
            },
        )

    if install_mode not in {"wheel", "path", "git"}:
        raise RuntimeError("--install-mode must be one of: repo, wheel, path, git")

    runtime_dir = run_dir / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    venv_root = runtime_dir / "venv"
    report: Dict[str, object] = {
        "mode": install_mode,
        "venvRoot": str(venv_root),
    }

    _run_checked_command(
        command=[sys.executable, "-m", "venv", str(venv_root)],
        cwd=repo_root,
        env=base_env,
        timeout_seconds=timeout_seconds,
        log_path=runtime_dir / "create-venv.log",
    )

    bin_dir = _venv_bin_dir(venv_root)
    venv_python = bin_dir / ("python.exe" if os.name == "nt" else "python")
    _run_checked_command(
        command=[str(venv_python), "-m", "pip", "install", "--upgrade", "pip"],
        cwd=repo_root,
        env=base_env,
        timeout_seconds=timeout_seconds,
        log_path=runtime_dir / "pip-upgrade.log",
    )

    install_spec = _install_spec_for_mode(
        mode=install_mode,
        repo_root=repo_root,
        install_target=install_target,
        venv_python=venv_python,
        runtime_dir=runtime_dir,
        base_env=base_env,
        timeout_seconds=timeout_seconds,
        report=report,
    )
    _run_checked_command(
        command=[str(venv_python), "-m", "pip", "install", install_spec],
        cwd=repo_root,
        env=base_env,
        timeout_seconds=timeout_seconds,
        log_path=runtime_dir / "pip-install.log",
    )

    runtime_env = dict(base_env)
    runtime_env["PATH"] = f"{bin_dir}{os.pathsep}{base_env.get('PATH', '')}"
    report["pythonBin"] = str(venv_python)
    report["binDir"] = str(bin_dir)
    report["setupCommand"] = str(bin_dir / "modeio-middleware-setup")
    report["gatewayCommand"] = str(bin_dir / "modeio-middleware-gateway")

    return RuntimeEnvironment(
        mode=install_mode,
        setup_command=[str(bin_dir / "modeio-middleware-setup")],
        gateway_command=[str(bin_dir / "modeio-middleware-gateway")],
        env=runtime_env,
        report=report,
    )
