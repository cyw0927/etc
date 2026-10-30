"""docs/preregistration_macro_alignment.md: live macro inputs use the training decision time."""
from datetime import datetime, timezone
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import alfred_research_features as af
import issue_macro_forward as issue

UTC = timezone.utc


def records():
    # August value known from 09-15; September value first published 10-27 (like M2 in 2026)
    return {s: [{'observation_date': '2026-08-01', 'realtime_start_date': '2026-09-15', 'realtime_end_date': None, 'value': 1.},
                {'observation_date': '2026-09-01', 'realtime_start_date': '2026-10-27', 'realtime_end_date': None, 'value': 2.}]
            for s in issue.SERIES}


def test_anchor_decision_is_training_decision_time():
    assert issue.anchor_decision('2026-10-28') == datetime(2026, 10, 28, 20, 15, tzinfo=UTC)
    with pytest.raises(ValueError):
        issue.anchor_decision('2026-10-31')  # Saturday: not a NYSE session


def test_inputs_do_not_depend_on_wall_clock_issue_time():
    # Old behaviour: the same anchor got different inputs before and after UTC midnight
    before, _ = issue.live_features(records(), datetime(2026, 10, 28, 23, 0, tzinfo=UTC))
    after, _ = issue.live_features(records(), datetime(2026, 10, 29, 2, 10, tzinfo=UTC))
    assert before != after
    values, evidence, decision = issue.input_features(records(), '2026-10-28')
    assert values == [1.] * 4 and decision == datetime(2026, 10, 28, 20, 15, tzinfo=UTC)
    assert all(e['observation_date'] == '2026-08-01' for e in evidence.values())


def test_live_inputs_equal_training_inputs_for_same_anchor():
    for anchor in ('2026-10-27', '2026-10-28', '2026-10-29', '2026-10-30'):
        live, _, decision = issue.input_features(records(), anchor)
        trained = af.historical_features(records(), pd.DatetimeIndex([decision]))
        assert live == trained.iloc[0].tolist(), anchor


def test_release_checked_september_inputs_start_with_anchor_1029():
    assert issue.input_features(records(), '2026-10-28')[0] == [1.] * 4  # Aug: release-checked v1 evidence fails
    assert issue.input_features(records(), '2026-10-29')[0] == [2.] * 4  # Sept: matches the fixed 2026-09 evidence
