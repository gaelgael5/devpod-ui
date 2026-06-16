from __future__ import annotations

import asyncio
import base64

import structlog
from fastapi import HTTPException

_log = structlog.get_logger(__name__)

SHELVE_SCRIPT = r"""#!/usr/bin/env bash
set -eu

if ! git rev-parse --git-dir >/dev/null 2>&1; then
  echo "NOTHING_TO_SHELVE"; exit 0
fi

dirty=0
[ -n "$(git status --porcelain)" ] && dirty=1

upstream="$(git rev-parse --abbrev-ref --symbolic-full-name @{u} 2>/dev/null || true)"
ahead=0
[ -n "$upstream" ] && ahead="$(git rev-list --count @{u}..HEAD 2>/dev/null || echo 0)"

if [ "$dirty" -eq 0 ] && [ "$ahead" -eq 0 ]; then
  echo "NOTHING_TO_SHELVE"; exit 0
fi

br="recovery-$(date +%d-%m-%y-%H-%M)"
i=1; base="$br"
while git ls-remote --exit-code --heads origin "$br" >/dev/null 2>&1; do
  i=$((i+1)); br="$base-$i"
done

git checkout -b "$br"
git add -A
git commit -m "WIP shelve $br" || true
git push -u origin "$br"
echo "SHELVED:$br"
"""


async def shelve_if_pending(
    devpod_bin: list[str],
    ws_id: str,
    env: dict[str, str],
) -> str | None:
    """Lance le script de shelve via devpod ssh.

    Retourne la branche créée, None si rien à shelver.
    Lève HTTPException(409) si le push échoue ou si devpod ssh échoue.
    """
    script_b64 = base64.b64encode(SHELVE_SCRIPT.strip().encode()).decode()
    cmd_str = f"echo {script_b64} | base64 -d | bash -l"
    cmd = [*devpod_bin, "ssh", ws_id, "--command", cmd_str]

    _log.info("workspace_shelve_start", ws_id=ws_id)
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_bytes, stderr_bytes = await proc.communicate()
    rc = proc.returncode
    stdout = stdout_bytes.decode(errors="replace").strip()
    stderr = stderr_bytes.decode(errors="replace").strip()

    _log.info("workspace_shelve_done", ws_id=ws_id, rc=rc)

    if rc == 0:
        for line in stdout.splitlines():
            if line.strip() == "NOTHING_TO_SHELVE":
                return None
            if line.strip().startswith("SHELVED:"):
                branch = line.strip()[len("SHELVED:"):]
                _log.info("workspace_shelved", ws_id=ws_id, branch=branch)
                return branch
        # rc=0 mais sortie inattendue — dégradation gracieuse (allow delete)
        _log.warning("workspace_shelve_unexpected_output", ws_id=ws_id, stdout_len=len(stdout))
        return None

    _log.warning("workspace_shelve_failed", ws_id=ws_id, rc=rc, stderr=stderr[:500])
    detail = (stderr[:200].strip()) or "Échec du push de la branche recovery"
    raise HTTPException(
        status_code=409,
        detail=f"Shelve impossible — suppression annulée. Détail : {detail}",
    )
