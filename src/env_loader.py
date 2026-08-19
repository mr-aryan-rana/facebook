"""Shared .env loader for the facebook/ package (server.py, mailer.py,
sender.py). Factored out of server.py's inline loader so all three read the
same files in the same precedence order instead of drifting."""

import os
from pathlib import Path

FACEBOOK_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = FACEBOOK_DIR.parent


def load_env() -> None:
    env_paths = [
        FACEBOOK_DIR / ".env.production",
        FACEBOOK_DIR / ".env.local",
        FACEBOOK_DIR / ".env",
        FACEBOOK_DIR / "src" / ".env",
        PROJECT_ROOT / ".env",
    ]
    for env_path in env_paths:
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if "=" in line and not line.strip().startswith("#"):
                    k, v = line.split("=", 1)
                    k_str = k.strip()
                    v_str = v.strip()
                    if k_str and v_str and k_str not in os.environ:
                        os.environ[k_str] = v_str
