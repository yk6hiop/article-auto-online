from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from online_app.deployment_readiness import collect_deployment_readiness


def main() -> int:
    result = collect_deployment_readiness()
    print("オンライン版 デプロイ前チェック")
    print("=" * 60)
    print(f"error={result['errors']} warning={result['warnings']}")
    print(f"deploy_smoke={result['ready_for_deploy_smoke']}")
    print(f"public_real_run={result['ready_for_public_real_run']}")
    print("-" * 60)
    for item in result["items"]:
        print(f"[{item.status}] {item.name}: {item.message}")
    print("-" * 60)
    print(json.dumps({
        "errors": result["errors"],
        "warnings": result["warnings"],
        "ready_for_deploy_smoke": result["ready_for_deploy_smoke"],
        "ready_for_public_real_run": result["ready_for_public_real_run"],
    }, ensure_ascii=False))
    return 0 if result["ready_for_deploy_smoke"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
