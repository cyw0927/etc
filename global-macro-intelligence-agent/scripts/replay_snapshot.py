"""Replay issued forecasts with their ORIGINAL code and pinned snapshots; never write the ledger.

The original run's commit is checked out into a temporary detached git worktree and the pipeline is
executed from there, so later commits on the current branch (new modules, bug fixes) neither block nor
alter the replay. Package versions must still match the original run.
"""
from __future__ import annotations
import argparse
import json
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

import gmia.config as config

PROJECT = config.PROJECT_ROOT
REPO = PROJECT.parent
BUNDLE = PROJECT / 'data/imported/gmia-audit-c0685423aafd'
ORIGINAL = BUNDLE / 'artifacts/runs/20261028T054452Z'
EXPECTED_COMMIT = '7fe1edb102bdcf754711463c68814b05d78db07f'

# Runs inside the original commit's source tree; the ledger writer is replaced by a no-op.
CHILD = r'''
import json, sys
from pathlib import Path
src, cfg_path, raw, artifacts, out = sys.argv[1:6]
sys.path.insert(0, src)
import gmia.config as config
config.ARTIFACTS_DIR = Path(artifacts)
import gmia.pipeline as pipeline
pipeline.append_forecasts = lambda *a, **k: {"mode": "replay_only", "inserted": 0, "ledger_written": False}
cfg = config.load_config(cfg_path)
cfg["data"]["raw_dir"] = raw
result = pipeline.run(cfg)
Path(out).write_text(json.dumps({"run_id": result["run_id"], "forecasts": result["forecasts"]}, default=str), encoding="utf-8")
'''


def verify_inputs(original, raw):
    from gmia.data.store import load_series
    for key, item in original['input_snapshots'].items():
        kind, sid = key.split('/', 1)
        folder = raw / ('market' if kind == 'market' else f'fred/{kind}')
        pointer = json.loads((folder / f'{sid}.snapshot.json').read_text(encoding='utf-8'))
        if item['integrity'] != 'sha256_verified' or pointer != item['pointer']:
            raise RuntimeError(f'Original pointer mismatch: {key}')
        _, meta = load_series(folder / f'{sid}.parquet')
        if meta['_integrity'] != 'sha256_verified':
            raise RuntimeError(f'Invalid snapshot: {key}')


def compare(expected, observed):
    def keyed(items):
        return {(x['target'], x['horizon']): x for x in items}
    a, b = keyed(expected), keyed(observed)
    if a.keys() != b.keys():
        raise RuntimeError('Forecast asset/horizon keys differ')
    mismatches, maximum, count = [], 0.0, 0
    for key in a:
        x, y = a[key], b[key]
        if x['forecast_date'] != y['forecast_date'] or x['selected_model'] != y['selected_model']:
            mismatches.append(str(key) + ' date/selection')
        if x['p_up_all_models'].keys() != y['p_up_all_models'].keys():
            mismatches.append(str(key) + ' candidate set')
            continue
        for model, p in x['p_up_all_models'].items():
            delta = abs(float(p) - float(y['p_up_all_models'][model]))
            maximum, count = max(maximum, delta), count + 1
            if delta > 1e-12:
                mismatches.append(f'{key} {model}: {delta}')
    return mismatches, maximum, count, len(a)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.parse_args()
    original = json.loads((ORIGINAL / 'run_meta.json').read_text(encoding='utf-8'))
    commit = original.get('git_commit')
    if commit != EXPECTED_COMMIT or original.get('code_state', {}).get('git_dirty') is not False:
        raise RuntimeError('Original run is not the expected clean recorded commit')
    installed = {k: version(k) for k in original['packages']}
    if installed != original['packages']:
        raise RuntimeError(f'Package versions differ: original={original["packages"]} installed={installed}')
    out = PROJECT / 'data/operations/replays' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + uuid.uuid4().hex[:8])
    out.mkdir(parents=True, exist_ok=False)
    raw = out / 'inputs/raw'
    shutil.copytree(BUNDLE / 'raw', raw)
    verify_inputs(original, raw)

    code = out / 'code'
    subprocess.run(['git', 'worktree', 'add', '--detach', str(code), commit], cwd=REPO, check=True,
                   stdout=subprocess.DEVNULL)
    try:
        src = code / PROJECT.name / 'src'
        result_file = out / 'replay_forecasts.json'
        subprocess.run([sys.executable, '-c', CHILD, str(src), str(ORIGINAL / 'config.yaml'), str(raw),
                        str(out / 'artifacts'), str(result_file)], cwd=out, check=True)
        replayed = json.loads(result_file.read_text(encoding='utf-8'))
    finally:
        subprocess.run(['git', 'worktree', 'remove', '--force', str(code)], cwd=REPO, check=False)

    expected = json.loads((ORIGINAL / 'forecasts.json').read_text(encoding='utf-8'))
    mismatches, maximum, count, n = compare(expected, replayed['forecasts'])
    summary = {'mode': 'replay_only_no_ledger_write', 'original_run': '20261028T054452Z',
               'original_git': commit, 'replayed_with': 'temporary detached worktree of original_git',
               'package_versions': installed, 'input_snapshots_verified': len(original['input_snapshots']),
               'asset_horizon_count': n, 'candidate_probabilities_checked': count,
               'max_abs_probability_difference': maximum, 'mismatches': mismatches,
               'replay_dir': str(out), 'output_run': replayed['run_id']}
    (out / 'replay_result.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if mismatches:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
