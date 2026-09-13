import logging
import tempfile

from inspect_ai import Task, task
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.util import sandbox

logger = logging.getLogger(__name__)

_COMPOSE = """services:
  default:
    image: docker.io/swrbr/threecb@sha256:sha256:735e85df031e1beeaea3432631bea3c626a682786e699a2a017162d2bba3bf5a
    command: "tail -f /dev/null"
"""


def _compose_file() -> str:
    f = tempfile.NamedTemporaryFile(suffix="-compose.yaml", delete=False, mode="w")
    f.write(_COMPOSE)
    f.close()
    return f.name


@task
def debug_postfix() -> Task:
    return Task(
        solver=run_debug(),
        dataset=MemoryDataset([Sample(input="debug", id="debug-postfix")]),
        sandbox=("k8s", _compose_file()),
        message_limit=2,
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
