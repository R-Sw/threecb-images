import logging
from pathlib import Path

from inspect_ai import Task, task
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.util import sandbox

logger = logging.getLogger(__name__)


@task
def debug_postfix() -> Task:
    return Task(
        solver=run_debug(),
        dataset=MemoryDataset([Sample(input="debug", id="debug-postfix")]),
        sandbox=("k8s", str(Path(__file__).parent / "compose.yaml")),
        message_limit=2,
    )


@task
def debug_entrypoints() -> Task:
    """Run each challenge image's entrypoint manually and capture output."""
    return Task(
        solver=run_entrypoint_debug(),
        dataset=MemoryDataset([Sample(input="debug", id="debug-entrypoints")]),
        message_limit=8,
    )


@solver
def run_debug() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        script = r"""
set -x
sed -i 's/myhostname = .*/myhostname = localhost/' /etc/postfix/main.cf
postfix check 2>&1 | head -20; echo CHECK_RC=$?
/etc/init.d/postfix restart 2>&1 | head -20; echo RESTART_RC=$?
postfix status 2>&1; echo STATUS_RC=$?
ls /var/spool/postfix/dev 2>&1 | head -5
echo testmail | mail -s test root@localhost 2>&1 | head -5; echo MAIL_RC=$?
sleep 4; cat /var/mail/root 2>&1 | head -10
"""
        result = await sandbox().exec(["bash", "-c", script], timeout=120)
        state.output.completion = "RC=%s\nSTDOUT:\n%s\nSTDERR:\n%s" % (
            result.returncode, result.stdout, result.stderr)
        state.completed = True
        return state
    return solve


@solver
def run_entrypoint_debug() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        result = await sandbox().exec(
            ["bash", "-c", "echo alive; ps aux 2>/dev/null | head -8; ls /challenge 2>&1; ls /root 2>&1 | head; cat /challenge/flag.txt 2>/dev/null | head -c 40"],
            timeout=30)
        state.output.completion = "RC=%s\nSTDOUT:\n%s\nSTDERR:\n%s" % (
            result.returncode, result.stdout, result.stderr)
        state.completed = True
        return state
    return solve
