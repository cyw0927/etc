"""장부 온라인 백업 및 무결성 검사. 덮어쓰기·자동실행·외부 업로드 없음."""

import argparse
import json
from pathlib import Path

from gmia.config import load_config
from gmia.evaluation.backup import backup_ledger
from gmia.evaluation.forward import ledger_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config")
    parser.add_argument("--destination", required=True, type=Path)
    args = parser.parse_args()
    result = backup_ledger(ledger_path(load_config(args.config)), args.destination)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
