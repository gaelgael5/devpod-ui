from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest


@pytest.mark.asyncio
async def test_runner_streams_output_to_log_file(
    tmp_data_root: Path, fake_devpod_bin: list[str]
) -> None:
    """Le subprocess streame stdout vers le fichier log."""
    import os

    from portal.devpod.runner import run_subprocess

    log_path = tmp_data_root / "test.log"
    env = {"PATH": os.environ.get("PATH", "")}

    returncode = await run_subprocess(
        cmd=[*fake_devpod_bin, "up", "--id", "alice-myapp"],
        env=env,
        log_path=log_path,
        ws_id="alice-myapp",
    )

    assert returncode == 0
    content = log_path.read_text(encoding="utf-8")
    assert "alice-myapp" in content


@pytest.mark.asyncio
async def test_runner_does_not_block_event_loop(
    tmp_data_root: Path, fake_devpod_bin: list[str]
) -> None:
    """Pendant le subprocess, l'event loop reste réactif."""
    import os

    from portal.devpod.runner import run_subprocess

    log_path = tmp_data_root / "test.log"
    env = {"PATH": os.environ.get("PATH", "")}
    counter = {"ticks": 0}

    async def ticker() -> None:
        for _ in range(5):
            await asyncio.sleep(0.01)
            counter["ticks"] += 1

    await asyncio.gather(
        run_subprocess(
            cmd=[*fake_devpod_bin, "up", "--id", "alice-myapp"],
            env=env,
            log_path=log_path,
            ws_id="alice-myapp",
        ),
        ticker(),
    )

    assert counter["ticks"] >= 3, "Event loop was blocked during subprocess"


@pytest.mark.asyncio
async def test_runner_lock_prevents_concurrent_up_on_same_ws_id(
    tmp_data_root: Path, fake_devpod_bin: list[str]
) -> None:
    """Deux run_subprocess concurrents sur le même ws_id sont sérialisés."""
    import os

    from portal.devpod.runner import clear_locks, run_subprocess

    clear_locks()
    log1 = tmp_data_root / "log1.log"
    log2 = tmp_data_root / "log2.log"
    env = {"PATH": os.environ.get("PATH", "")}

    start_times: list[float] = []
    end_times: list[float] = []

    async def timed_run(log: Path) -> None:
        start_times.append(time.monotonic())
        await run_subprocess(
            cmd=[*fake_devpod_bin, "up", "--id", "alice-myapp"],
            env=env,
            log_path=log,
            ws_id="alice-myapp",
        )
        end_times.append(time.monotonic())

    await asyncio.gather(timed_run(log1), timed_run(log2))

    assert len(end_times) == 2
    # Avec sérialisation, le premier end_time doit précéder le second start_time
    # (ou au moins : la durée totale est ~2x la durée d'un seul)
    total_duration = max(end_times) - min(start_times)
    single_duration = 0.05  # fake_devpod sleep 0.05s
    assert total_duration >= single_duration * 1.5, (
        f"Expected serialized runs (total ≈ 2x{single_duration:.2f}s), got {total_duration:.2f}s"
    )
    clear_locks()


@pytest.mark.asyncio
async def test_runner_different_ws_ids_run_concurrently(
    tmp_data_root: Path, fake_devpod_bin: list[str]
) -> None:
    """Deux ws_id différents s'exécutent en parallèle."""
    import os

    from portal.devpod.runner import clear_locks, run_subprocess

    clear_locks()
    log_warm = tmp_data_root / "log_warm.log"
    log1 = tmp_data_root / "log1.log"
    log2 = tmp_data_root / "log2.log"
    env = {"PATH": os.environ.get("PATH", "")}

    # Mesurer le temps réel d'un seul run (inclut le startup Python sur Windows)
    t0 = time.monotonic()
    await run_subprocess(
        cmd=[*fake_devpod_bin, "up", "--id", "warm-up"],
        env=env,
        log_path=log_warm,
        ws_id="warm-up",
    )
    single_duration = time.monotonic() - t0

    clear_locks()
    t_start = time.monotonic()
    await asyncio.gather(
        run_subprocess(
            cmd=[*fake_devpod_bin, "up", "--id", "alice-app1"],
            env=env,
            log_path=log1,
            ws_id="alice-app1",
        ),
        run_subprocess(
            cmd=[*fake_devpod_bin, "up", "--id", "alice-app2"],
            env=env,
            log_path=log2,
            ws_id="alice-app2",
        ),
    )
    elapsed = time.monotonic() - t_start

    # En parallèle, temps total < 1.5x la durée d'un seul run séquentiel
    assert elapsed < single_duration * 1.5, (
        f"Expected parallel execution: elapsed={elapsed:.2f}s, single={single_duration:.2f}s"
    )
    clear_locks()
