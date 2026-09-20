"""PulseAudio devices used as the runtime-neutral voice bridge boundary.

The call transport speaks PCM frames while external runtimes may expect regular
audio devices. This module creates one virtual source and sink per call.
"""

from __future__ import annotations

import asyncio
import os
import re
import secrets
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from loguru import logger

from core.params import runtime_settings

from .models import DEFAULT_CHANNELS, DEFAULT_SAMPLE_RATE, VOICE_ROOT

_SAMPLE_BYTES = 2


class PulseAudioUnavailable(RuntimeError):
    """Raised when the local PulseAudio bridge cannot be prepared."""


@dataclass(frozen=True, slots=True)
class PulseAudioConfig:
    """Filesystem and PCM settings for the shared PulseAudio server."""

    root: Path = VOICE_ROOT
    sample_rate: int = DEFAULT_SAMPLE_RATE
    channels: int = DEFAULT_CHANNELS
    frame_ms: int = 20

    @classmethod
    def from_settings(cls) -> "PulseAudioConfig":
        return cls(
            root=VOICE_ROOT,
            sample_rate=runtime_settings.VOICE_SAMPLE_RATE,
            channels=runtime_settings.VOICE_CHANNELS,
        )

    @property
    def pulse_dir(self) -> Path:
        return self.root / "pulse"

    @property
    def runtime_dir(self) -> Path:
        return self.root / "runtime"

    @property
    def socket_path(self) -> Path:
        return self.pulse_dir / "native"

    @property
    def pulse_server(self) -> str:
        return f"unix:{self.socket_path}"

    @property
    def frame_bytes(self) -> int:
        return self.sample_rate * self.channels * _SAMPLE_BYTES * self.frame_ms // 1000

    def env(self) -> dict[str, str]:
        env = os.environ.copy()
        env["PULSE_SERVER"] = self.pulse_server
        env["XDG_RUNTIME_DIR"] = str(self.runtime_dir)
        return env

    def prepare_directories(self) -> None:
        for path in (self.root, self.pulse_dir):
            path.mkdir(parents=True, exist_ok=True)
            _chmod_best_effort(path, 0o1777)
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        _chmod_best_effort(self.runtime_dir, 0o700)


@dataclass(slots=True)
class PulseAudioDevices:
    """Per-call PulseAudio source/sink pair."""

    config: PulseAudioConfig
    call_id: str
    mic_sink_name: str
    source_name: str
    sink_name: str
    module_ids: list[int] = field(default_factory=lambda: [])
    extra_module_ids: list[int] = field(default_factory=lambda: [])

    @property
    def sink_monitor(self) -> str:
        return f"{self.sink_name}.monitor"

    @property
    def env(self) -> dict[str, str]:
        return self.config.env()

    def runtime_env(self) -> dict[str, str]:
        """Environment exposed to an external voice runtime."""
        return {
            "PULSE_SERVER": self.config.pulse_server,
            "XDG_RUNTIME_DIR": str(self.config.runtime_dir),
            "GALARIS_VOICE_SOURCE": self.source_name,
            "GALARIS_VOICE_MIC_SINK": self.mic_sink_name,
            "GALARIS_VOICE_SINK": self.sink_name,
        }

    async def connect_loopback(self, latency_ms: int = 50) -> int:
        """Loop the virtual microphone into the virtual speaker.

        This is only for manual diagnostics: Talk -> Pulse source -> Pulse sink -> Talk.
        """
        module_id = await _load_module(
            self.config,
            "module-loopback",
            [
                f"source={self.source_name}",
                f"sink={self.sink_name}",
                f"latency_msec={latency_ms}",
            ],
        )
        self.extra_module_ids.append(module_id)
        logger.info(
            "PulseAudio: loopback loaded source={} sink={} module={}",
            self.source_name,
            self.sink_name,
            module_id,
        )
        return module_id


class PulseAudioBridge:
    """Async context manager creating and cleaning call devices."""

    def __init__(self, call_id: str, config: PulseAudioConfig | None = None) -> None:
        self._call_id = call_id
        self._config = config or PulseAudioConfig.from_settings()
        self._devices: PulseAudioDevices | None = None

    async def __aenter__(self) -> PulseAudioDevices:
        await ensure_pulseaudio(self._config)
        self._devices = await create_call_devices(self._call_id, self._config)
        return self._devices

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self._devices is not None:
            await cleanup_call_devices(self._devices)


async def ensure_pulseaudio(config: PulseAudioConfig | None = None) -> None:
    """Ensure the shared PulseAudio daemon is reachable."""
    config = config or PulseAudioConfig.from_settings()
    missing = [tool for tool in ("pactl", "pacat", "parec") if shutil.which(tool) is None]
    if missing:
        raise PulseAudioUnavailable(
            "PulseAudio tools are missing from the backend: " + ", ".join(missing)
        )

    config.prepare_directories()
    if await _pactl_ok(config, ["info"], timeout=3.0):
        logger.debug("PulseAudio server is already available at {}", config.pulse_server)
        return

    if shutil.which("pulseaudio") is None:
        raise PulseAudioUnavailable("The pulseaudio binary is missing from the backend.")

    logger.info("PulseAudio: starting shared server at {}", config.pulse_server)
    start_args = ["pulseaudio"]
    if os.geteuid() == 0:
        # The dev backend currently runs as root. PulseAudio user mode refuses root,
        # so we use system mode for this container-only daemon.
        start_args.append("--system")
    start_args.extend([
        "--daemonize=yes",
        "--exit-idle-time=-1",
        "--disallow-exit",
        (
            "--load=module-native-protocol-unix "
            f"socket={config.socket_path} auth-anonymous=1"
        ),
    ])
    await _run_command(
        start_args,
        config,
        timeout=10.0,
        check=True,
    )

    for _ in range(30):
        if await _pactl_ok(config, ["info"], timeout=2.0):
            logger.info("PulseAudio: server ready on {}", config.pulse_server)
            return
        await asyncio.sleep(0.2)
    raise PulseAudioUnavailable(f"PulseAudio is not responding at {config.pulse_server}.")


async def create_call_devices(
    call_id: str,
    config: PulseAudioConfig | None = None,
) -> PulseAudioDevices:
    """Create a source/sink pair for one call."""
    config = config or PulseAudioConfig.from_settings()
    config.prepare_directories()

    prefix = _device_prefix(call_id)
    mic_sink_name = f"{prefix}_mic"
    source_name = f"{mic_sink_name}.monitor"
    sink_name = f"{prefix}_speaker"

    devices = PulseAudioDevices(
        config=config,
        call_id=call_id,
        mic_sink_name=mic_sink_name,
        source_name=source_name,
        sink_name=sink_name,
    )
    try:
        mic_module = await _load_module(
            config,
            "module-null-sink",
            [
                f"sink_name={mic_sink_name}",
                "format=s16le",
                f"rate={config.sample_rate}",
                f"channels={config.channels}",
                f"sink_properties=device.description={mic_sink_name}",
            ],
        )
        sink_module = await _load_module(
            config,
            "module-null-sink",
            [
                f"sink_name={sink_name}",
                "format=s16le",
                f"rate={config.sample_rate}",
                f"channels={config.channels}",
                f"sink_properties=device.description={sink_name}",
            ],
        )
        devices.module_ids.extend([mic_module, sink_module])
        logger.info(
            "PulseAudio: call devices ready source={} mic_sink={} sink={}",
            source_name,
            mic_sink_name,
            sink_name,
        )
        return devices
    except Exception:
        await cleanup_call_devices(devices)
        raise


async def cleanup_call_devices(devices: PulseAudioDevices) -> None:
    """Unload modules and remove the FIFO for a call."""
    for module_id in reversed([*devices.extra_module_ids, *devices.module_ids]):
        await _pactl_ok(devices.config, ["unload-module", str(module_id)], timeout=5.0)
    devices.extra_module_ids.clear()
    devices.module_ids.clear()

    logger.info("PulseAudio: call devices cleaned up call_id={}", devices.call_id)


async def pulseaudio_status(config: PulseAudioConfig | None = None) -> dict[str, str]:
    """Return compact diagnostic data for manual tests."""
    config = config or PulseAudioConfig.from_settings()
    await ensure_pulseaudio(config)
    return {
        "info": await _pactl(config, ["info"]),
        "sources": await _pactl(config, ["list", "short", "sources"]),
        "sinks": await _pactl(config, ["list", "short", "sinks"]),
    }


async def _load_module(
    config: PulseAudioConfig,
    module: str,
    args: Iterable[str],
) -> int:
    output = (await _pactl(config, ["load-module", module, *args])).strip()
    try:
        return int(output.splitlines()[-1])
    except (IndexError, ValueError) as exc:
        raise PulseAudioUnavailable(
            f"PulseAudio loaded {module}, but the module ID is unreadable: {output!r}"
        ) from exc


async def _pactl(config: PulseAudioConfig, args: list[str], timeout: float = 10.0) -> str:
    return await _run_command(["pactl", *args], config, timeout=timeout, check=True)


async def _pactl_ok(
    config: PulseAudioConfig,
    args: list[str],
    timeout: float = 10.0,
) -> bool:
    try:
        await _run_command(["pactl", *args], config, timeout=timeout, check=True)
        return True
    except PulseAudioUnavailable:
        return False


async def _run_command(
    args: list[str],
    config: PulseAudioConfig,
    *,
    timeout: float,
    check: bool,
) -> str:
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=config.env(),
        )
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError as exc:
        raise PulseAudioUnavailable(
            f"Commande PulseAudio en timeout: {' '.join(args)}"
        ) from exc
    except FileNotFoundError as exc:
        raise PulseAudioUnavailable(f"Command not found: {args[0]}") from exc

    stdout = stdout_b.decode(errors="replace")
    stderr = stderr_b.decode(errors="replace")
    if check and proc.returncode != 0:
        detail = (stderr or stdout).strip()
        raise PulseAudioUnavailable(
            f"Commande PulseAudio echouee ({proc.returncode}): {' '.join(args)}"
            + (f" -- {detail}" if detail else "")
        )
    return stdout


def _device_prefix(call_id: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_]+", "_", call_id).strip("_").lower() or "call"
    return f"galaris_voice_{safe[:32]}_{secrets.token_hex(3)}"


def _chmod_best_effort(path: Path, mode: int) -> None:
    try:
        path.chmod(mode)
    except OSError as exc:
        logger.debug("PulseAudio: ignored chmod failure on {} ({})", path, exc)
