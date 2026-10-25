"""Environment for system programs launched from a frozen application."""

import os
import sys


def system_process_env() -> dict[str, str]:
    env = os.environ.copy()
    if getattr(sys, "frozen", False):
        for name in ("LD_LIBRARY_PATH", "LIBPATH"):
            original = env.pop(name + "_ORIG", None)
            env.pop(name, None)
            if original is not None:
                env[name] = original
    return env
