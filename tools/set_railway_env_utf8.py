from __future__ import annotations

import subprocess
import sys
import shutil
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python tools/set_railway_env_utf8.py <env-file>")
        return 2

    env_path = Path(sys.argv[1])
    if not env_path.exists():
        print(f"env file not found: {env_path}")
        return 1

    railway_bin = shutil.which("railway") or shutil.which("railway.cmd")
    if not railway_bin:
        print("railway CLI not found in PATH")
        return 1

    keys: list[str] = []
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        subprocess.run(
            [
                railway_bin,
                "variable",
                "set",
                key,
                "--stdin",
                "--skip-deploys",
                "--service",
                "web",
                "--environment",
                "production",
            ],
            input=value,
            text=True,
            encoding="utf-8",
            check=True,
            stdout=subprocess.DEVNULL,
        )
        keys.append(key)

    print("set_keys=" + ",".join(keys))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
