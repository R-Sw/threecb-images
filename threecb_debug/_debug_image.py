"""Platform sanity checks for the 3CB k8s challenge images.

For each challenge image (digest-pinned, same as task_configs/<challenge>/
compose.yaml on the 3cb-hawk branch), run the checks that failed in the
35-sample verification runs before the corresponding fixes:

- every k8s sandbox exec is wrapped in GNU `timeout -k 5s <n>s`: alpine 3.14
  busybox 1.33 rejects `-k`, so execs on evasion_debugger/find_all_users
  failed with 'timeout: unrecognized option: k' until GNU coreutils was
  installed in the images (both the wrapper path and the in-container
  `timeout -k` binary are checked);
- /tmp must be world-writable with the sticky bit (1777), like the upstream
  base images, so agents can use it as scratch space;
- /home/challenge_user must be owned by uid 1000 (like `adduser`/`useradd
  --create-home` in a real Docker build), so the login shell can source the
  dotfiles and the agent can write to its home;
- exec as the challenge user must work in the image working directory
  (python_repl_factorial10: WORKDIR /root, non-root agent).
"""

import json
import logging
import tempfile

from inspect_ai import Task, task
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.util import sandbox

logger = logging.getLogger(__name__)

# digests of the images pushed from the 3cb-hawk branch (09915118)
IMAGES = {
    "evasion_debugger": {
        "digest": "sha256:5844186bbcb0c4f568a1e73b710c2ed9d6b5bdc6d9b2a0c8ba3ff33924d56641",
        "user": "challenge_user",
        "checks": "timeout",
    },
    "find_all_users": {
        "digest": "sha256:cfb519e6df0cb5d6441d0de5ce3dab72976e5cbba5186441c8e56cd06069c6f6",
        "user": "root",
        "checks": "unusual_homes",
    },
    "web_navigation": {
        "digest": "sha256:617727aae1fde07c00dcb1cb5057401b42b788b460317a9f4b396994ba4d860e",
        "user": "challenge_user",
        "checks": "wrt_home",
    },
    "python_repl_factorial10": {
        "digest": "sha256:245174bd379ec2fb2a590ee25c023bf97e5865842b4c1ef95f57eaa1af8a0ca2",
        "user": "challenge_user",
        "checks": "workdir_root",
    },
}

SCRIPTS = {
    "timeout": r"""
which timeout; ls -la $(which timeout)
timeout -k 5s 3s sleep 10; echo INCONTAINER_TIMEOUT_RC=$?
ls -ld /tmp; touch /tmp/wtest 2>&1 && echo TMP_WRITABLE=yes || echo TMP_WRITABLE=no
""",
    "unusual_homes": r"""
which timeout; ls -la $(which timeout)
timeout -k 5s 3s sleep 10; echo INCONTAINER_TIMEOUT_RC=$?
ls -ld /tmp /var/unusual_home /opt/phantom_home
touch /tmp/wtest 2>&1 && echo TMP_WRITABLE=yes || echo TMP_WRITABLE=no
""",
    "wrt_home": r"""
id
ls -ld /tmp /home/challenge_user
touch /tmp/wtest 2>&1 && echo TMP_WRITABLE=yes || echo TMP_WRITABLE=no
touch /home/challenge_user/wtest 2>&1 && echo HOME_WRITABLE=yes || echo HOME_WRITABLE=no
""",
    "workdir_root": r"""
pwd
id
python3 -c 'print(10*9*8*7*6*5*4*3*2*1)'
""",
}


def _compose_file(digest: str) -> str:
    content = (
        "services:\n"
        "  default:\n"
        f"    image: docker.io/swrbr/threecb@{digest}\n"
        '    command: "tail -f /dev/null"\n'
    )
    f = tempfile.NamedTemporaryFile(suffix="-compose.yaml", delete=False, mode="w")
    f.write(content)
    f.close()
    return f.name


@task
def debug_image() -> Task:
    samples = []
    for name, spec in IMAGES.items():
        samples.append(
            Sample(
                input="debug",
                id=f"debug-{name}",
                sandbox=("k8s", _compose_file(spec["digest"])),
            )
        )
    return Task(
        solver=run_debug(),
        dataset=MemoryDataset(samples),
        message_limit=2,
    )


@solver
def run_debug() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        spec = IMAGES[state.sample_id.replace("debug-", "")]
        script = SCRIPTS[spec["checks"]]
        # 1) the sandbox exec wrapper itself prefixes `timeout -k 5s <n>s`:
        #    a busybox timeout without -k fails here.
        wrapped = await sandbox().exec(
            ["bash", "-c", script], user=spec["user"], timeout=60
        )
        # 2) a command that overruns its timeout: the wrapper must kill it
        #    (rc 124 with GNU timeout) instead of erroring on the -k flag.
        overrun = None
        if "timeout" in spec["checks"]:
            overrun = await sandbox().exec(
                ["bash", "-c", "sleep 30"], user=spec["user"], timeout=3
            )
        state.output.completion = json.dumps(
            {
                "id": state.sample_id,
                "wrapped": {
                    "returncode": wrapped.returncode,
                    "stdout": wrapped.stdout,
                    "stderr": wrapped.stderr,
                },
                "overrun": None
                if overrun is None
                else {
                    "returncode": overrun.returncode,
                    "stdout": overrun.stdout,
                    "stderr": overrun.stderr,
                },
            },
            indent=1,
        )
        state.completed = True
        return state

    return solve
