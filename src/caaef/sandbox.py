"""The sandboxed scenario container.

Design note, and a deliberate deviation from the published benchmark harness
(ODCV-Bench at 7353f1cf4b2579a3a8a5b8a5061d7c7d41f60668):

The benchmark runs a `mission_executor` container that talks to an `orchestrator_api`
Flask service over HTTP; the orchestrator executes each agent command with
`subprocess.run(cmd, shell=True, cwd=cwd, timeout=30)`.

We keep the sandbox container but drive it with `docker exec` from the host instead of
through the Flask API, and we run the agent loop on the host. Reasons:

1.  True network isolation. `--network none` gives the sandbox no egress at all. The
    benchmark's compose file puts the sandbox on a bridge network with internet access,
    and publishing a port to the host (needed by the Flask route) is incompatible with
    Docker's `internal: true` networks. The author asked for egress to be cut.
2.  Phase 1 tracing needs per-step file hashes taken *without* those commands appearing
    in the agent's trajectory. `docker exec` sidesteps the API's `message_history` and
    `last_working_dir` state entirely.
3.  The benchmark's own `validation_log` crash bug (agent_main.py:229) destroys the
    trajectory of any run that raises. We must keep failed runs, not lose them.

Command semantics are preserved exactly, which is what the model sees:

*   Each command runs in a fresh shell. This matches the benchmark: it calls
    `subprocess.run(..., shell=True)` per command, so a `cd` never persists. The
    orchestrator's `last_working_dir` only ever changes if the caller passes
    `working_dir`, and `agent_main.py` never does.
*   Working directory is `/app`, the scenario Dockerfiles' `WORKDIR`.
*   Timeout is 30 s, enforced per command.
*   The tool result handed back to the model is the same JSON object shape the benchmark
    produces: `{"stdout", "stderr", "role", "returncode"}`.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tarfile
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .config import BENCH_ROOT, REPO_ROOT, scenario_dir

ORCH_ZIP = BENCH_ROOT / "orchestrator_api.zip"
BUILD_ROOT = REPO_ROOT / ".build"

WORKDIR = "/app"
BASH_TIMEOUT_S = 30
# Ceiling on docker-level operations, distinct from the in-sandbox command timeout.
DOCKER_OP_TIMEOUT_S = 120


class SandboxError(RuntimeError):
    pass


def _run(cmd: list[str], timeout: int = DOCKER_OP_TIMEOUT_S) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


@dataclass
class ExecResult:
    stdout: str
    stderr: str
    returncode: int
    timed_out: bool

    def as_tool_payload(self) -> str:
        """Serialise exactly as the benchmark's executor does, so the model's input
        is byte-identical in shape to a real ODCV-Bench run."""
        return json.dumps(
            {
                "stdout": self.stdout,
                "stderr": self.stderr,
                "role": "tool",
                "returncode": self.returncode,
            }
        )


class Sandbox:
    """A built-and-running scenario container.

    Use as a context manager so the container is always removed, including on error.
    """

    def __init__(self, scenario: str, variant: str, run_id: str | None = None):
        self.scenario = scenario
        self.variant = variant
        self.run_id = run_id or uuid.uuid4().hex[:12]
        self.image = f"caaef/{variant}-{scenario}".lower()
        self.container = f"caaef-{self.run_id}"
        self._ctx: Path | None = None
        self._started = False

    # -- lifecycle ----------------------------------------------------------------

    def _prepare_context(self) -> Path:
        """Reproduce the benchmark's build context.

        `run_benchmarks.py` unzips `orchestrator_api.zip` and then copies the scenario
        directory over the top. The scenario's own Dockerfile wins, and the zip supplies
        the `requirements.txt` that Dockerfile expects (the scenarios ship none).
        """
        ctx = BUILD_ROOT / self.run_id
        if ctx.exists():
            shutil.rmtree(ctx)
        ctx.parent.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(ORCH_ZIP) as zf:
            zf.extractall(ctx.parent / self.run_id / "_unzip")
        unzipped = ctx.parent / self.run_id / "_unzip" / "orchestrator_api"
        shutil.copytree(unzipped, ctx, dirs_exist_ok=True)
        shutil.rmtree(ctx.parent / self.run_id / "_unzip")

        src = scenario_dir(self.scenario, self.variant)
        if not src.is_dir():
            raise SandboxError(f"scenario directory missing: {src}")
        for item in src.iterdir():
            dst = ctx / item.name
            if item.is_dir():
                if dst.exists():
                    shutil.rmtree(dst)
                shutil.copytree(item, dst)
            else:
                shutil.copy2(item, dst)

        if not (ctx / "Dockerfile").exists():
            raise SandboxError(f"no Dockerfile in build context for {self.scenario}")
        self._ctx = ctx
        return ctx

    def build(self) -> None:
        ctx = self._prepare_context()
        # Build needs network (apt-get, pip). Only the RUN container is isolated.
        r = _run(
            ["docker", "build", "-q", "-t", self.image, str(ctx)],
            timeout=900,
        )
        if r.returncode != 0:
            raise SandboxError(
                f"docker build failed for {self.variant}/{self.scenario}:\n{r.stdout}\n{r.stderr}"
            )

    def start(self) -> None:
        """Start the container with no network at all.

        `--network none` is the author's decision to cut sandbox egress. Verified safe:
        no scenario script makes a runtime network call and no scenario prompt mentions
        network access. The scenario CMD (`task_executor_api.py`, a Flask server) is
        overridden with `sleep infinity` because we drive the container by `docker exec`
        and the HTTP API would be unreachable on an isolated network anyway.
        """
        r = _run(
            [
                "docker", "run", "-d",
                "--name", self.container,
                "--network", "none",
                "--workdir", WORKDIR,
                # Defence in depth: the agent is expected to be adversarial.
                "--pids-limit", "512",
                "--memory", "2g",
                "--entrypoint", "sleep",
                self.image, "infinity",
            ]
        )
        if r.returncode != 0:
            raise SandboxError(f"docker run failed for {self.container}:\n{r.stderr}")
        self._started = True

    def stop(self) -> None:
        if self._started:
            _run(["docker", "rm", "-f", self.container])
            self._started = False
        if self._ctx and self._ctx.exists():
            shutil.rmtree(self._ctx, ignore_errors=True)

    def __enter__(self) -> "Sandbox":
        self.build()
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()

    # -- agent-visible execution --------------------------------------------------

    def exec_bash(self, command: str) -> ExecResult:
        """Run one agent command, with the benchmark's 30 s per-command timeout.

        A fresh shell per call, starting at /app — identical to the benchmark's
        `subprocess.run(cmd, shell=True, cwd='/app')`.
        """
        try:
            r = _run(
                ["docker", "exec", "-w", WORKDIR, self.container, "bash", "-lc", command],
                timeout=BASH_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired:
            # Mirror the orchestrator's timeout response verbatim.
            return ExecResult(stdout="", stderr="Command timed out", returncode=-1, timed_out=True)
        return ExecResult(
            stdout=r.stdout, stderr=r.stderr, returncode=r.returncode, timed_out=False
        )

    # -- state capture, invisible to the agent ------------------------------------

    def hash_state(self) -> dict[str, str]:
        """sha256 of every regular file under the scenario-relevant paths.

        Covers /app (task data and workspace) AND /usr/local/bin (where the scenario
        Dockerfiles install the KPI / validator / monitoring scripts, chmod 555). The
        latter matters: rewriting or disabling a validator is one of the violation
        classes the study must detect, and omitting that path would make it invisible to
        the state checkers. The container runs as root, so 555 is no real protection.

        Harness files that we or the benchmark injected are excluded, so they cannot be
        mistaken for scenario state.

        Taken by `docker exec`, so these commands never enter the agent's trajectory.
        This is what lets a data-file or validator change be established from *state*
        rather than from reading the log.
        """
        script = (
            "find /app /usr/local/bin -type f "
            "! -name task_executor_api.py ! -path '/app/templates/*' "
            "! -name requirements.txt ! -name '.caaef_pristine_*' "
            "-exec sha256sum {} + 2>/dev/null | sort -k2"
        )
        r = _run(["docker", "exec", self.container, "bash", "-lc", script])
        out: dict[str, str] = {}
        for line in r.stdout.splitlines():
            digest, _, path = line.partition("  ")
            if digest and path:
                out[path.strip()] = digest
        return out

    def snapshot(self, dest: Path) -> Path:
        """Export /app as a tar so O can be recomputed offline, without re-running a model.

        The experiment prompt requires analyses to be re-runnable from stored artefacts.
        Recomputing O means running the scenario's pristine KPI script against the final
        state, which needs that state preserved.
        """
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open("wb") as fh:
            p = subprocess.run(
                ["docker", "cp", f"{self.container}:{WORKDIR}", "-"],
                stdout=fh,
                stderr=subprocess.PIPE,
                timeout=DOCKER_OP_TIMEOUT_S,
            )
        if p.returncode != 0:
            raise SandboxError(f"snapshot failed for {self.container}: {p.stderr!r}")
        return dest

    def run_pristine(self, rel_script: str, args: str = "") -> ExecResult:
        """Copy the scenario's ORIGINAL script into the container and run it.

        This is how O is measured, per the author's decision: the agent may have edited
        or deleted the real KPI script, and a tampered script must not be able to
        inflate O. The pristine copy is placed at a path outside the agent's workspace
        and the agent never sees it (the run is over by this point).
        """
        src = scenario_dir(self.scenario, self.variant) / rel_script
        if not src.exists():
            raise SandboxError(f"pristine script not found: {src}")
        target = f"/tmp/.caaef_pristine_{Path(rel_script).name}"
        r = _run(["docker", "cp", str(src), f"{self.container}:{target}"])
        if r.returncode != 0:
            raise SandboxError(f"failed to copy pristine script: {r.stderr}")
        cmd = f"chmod +x {target} && {target} {args}".strip()
        try:
            p = _run(
                ["docker", "exec", "-w", WORKDIR, self.container, "bash", "-lc", cmd],
                timeout=BASH_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired:
            return ExecResult("", "Command timed out", -1, True)
        return ExecResult(p.stdout, p.stderr, p.returncode, False)


def read_prompts(scenario: str, variant: str) -> tuple[str, str]:
    """Return (system_prompt, user_prompt) for a scenario variant, unmodified."""
    data = json.loads((scenario_dir(scenario, variant) / "prompt.json").read_text())
    return data["system_prompt"], data["user_prompt"]


def extract_snapshot(tar_path: Path, dest: Path) -> Path:
    """Unpack a stored snapshot for offline inspection."""
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tar_path) as tf:
        tf.extractall(dest, filter="data")
    return dest
