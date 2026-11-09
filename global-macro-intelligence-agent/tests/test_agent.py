"""Research agent prototype: sources, as-of gating, no look-ahead, memo rules, error injection, loop."""
import json
import math
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from gmia.agent import sources
from gmia.agent.agent import run
from gmia.agent.inject import RULE_EXPECTED, meaning_mutants, rule_mutants
from gmia.agent.memo import allowed_numbers, render, verify
from gmia.agent.sources import Observation, available_utc, parse_h10, parse_treasury_csv
from gmia.agent.tools import ToolContext, ToolError, conditional_outcomes, get_change, get_latest, list_series


def business_days(start: date, n: int) -> list[date]:
    days, day = [], start
    while len(days) < n:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    return days


def series(series_id: str, values: list[float], start: date = date(2020, 1, 1)) -> list[Observation]:
    return [Observation(series_id, d, v, available_utc(series_id, d), "sha-" + series_id, "snap")
            for d, v in zip(business_days(start, len(values)), values)]


def synthetic(n: int = 900) -> dict:
    real = [1.0 + 0.5 * math.sin(i / 23) + 0.002 * i for i in range(n)]
    krw = [1100 * (1 + 0.04 * math.sin(i / 31) + 0.0001 * i) for i in range(n)]
    nominal = [r + 2.0 for r in real]
    return {"UST_REAL_10Y": series("UST_REAL_10Y", real), "UST_NOM_10Y": series("UST_NOM_10Y", nominal),
            "USDKRW": series("USDKRW", krw)}


def test_treasury_parser_finds_tenor_column_by_name_and_skips_missing():
    raw = b'Date,"5 YR","10 YR"\n10/30/2026,2.25,2.60\n10/29/2026,2.31,N/A\n'
    assert parse_treasury_csv(raw, "10 YR") == [(date(2026, 10, 30), 2.60)]
    assert parse_treasury_csv(b'Date,"10 Yr"\n01/02/2003,4.00\n', "10 Yr") == [(date(2003, 1, 2), 4.0)]
    assert parse_treasury_csv(raw, "30 YR") == []


def test_h10_parser_skips_no_data_rows():
    raw = (b'<th id="r1" headers="a1"> 3-JAN-00 </th>\n<td headers="a2 a1 r1">  1128.0000 </td>'
           b'<th id="r1" headers="a1">25-DEC-25 </th><td headers="a2 a1 r1">   ND   </td>')
    assert parse_h10(raw) == [(date(2000, 1, 3), 1128.0)]


def test_availability_rules_are_conservative():
    assert available_utc("UST_REAL_10Y", date(2026, 10, 30)) == datetime(2026, 10, 31, 10, 0, tzinfo=timezone.utc)
    # H.10 publishes a week's values on the following Monday; the rule waits until Tuesday 17:00 ET.
    friday, monday = date(2026, 10, 23), date(2026, 10, 19)
    assert available_utc("USDKRW", friday) == datetime(2026, 10, 27, 21, 0, tzinfo=timezone.utc)
    assert available_utc("USDKRW", monday) == available_utc("USDKRW", friday)


def test_get_latest_withholds_values_not_yet_available():
    data = synthetic()
    last_week = data["USDKRW"][-5:]
    as_of = last_week[0].available_utc - timedelta(seconds=1)
    out = get_latest(ToolContext(as_of, data), "USDKRW", 3)
    assert out["observations"][-1]["date"] < last_week[0].obs_date.isoformat()
    withheld = sum(o.available_utc > as_of for o in data["USDKRW"])
    assert withheld >= 5 and f"{withheld} later observations" in out["note"]


def test_every_evidence_is_available_at_as_of():
    data = synthetic()
    as_of = data["USDKRW"][600].available_utc
    ctx = ToolContext(as_of, data)
    list_series(ctx)
    get_change(ctx, "UST_REAL_10Y", 20)
    conditional_outcomes(ctx, "UST_REAL_10Y", 20, "rise", 0.1, "USDKRW", 20)
    assert ctx.registry.items
    assert all(datetime.fromisoformat(e.available_utc) <= as_of for e in ctx.registry.items.values())


def test_conditional_outcomes_ignore_values_after_as_of():
    data = synthetic()
    as_of = data["USDKRW"][600].available_utc
    before = conditional_outcomes(ToolContext(as_of, data), "UST_REAL_10Y", 20, "rise", 0.1, "USDKRW", 20)
    shocked = {k: [o if o.available_utc <= as_of else Observation(o.series_id, o.obs_date, o.value * 3,
                                                                  o.available_utc, o.file_sha256, o.snapshot)
                   for o in v] for k, v in data.items()}
    after = conditional_outcomes(ToolContext(as_of, shocked), "UST_REAL_10Y", 20, "rise", 0.1, "USDKRW", 20)
    strip = lambda d: {k: v["value"] for k, v in d.items()}  # noqa: E731
    assert strip(before["episodes"]) == strip(after["episodes"])
    assert strip(before["all_days_baseline"]) == strip(after["all_days_baseline"])


def test_conditional_outcomes_refuse_thin_samples():
    with pytest.raises(ToolError):
        conditional_outcomes(ToolContext(datetime(2030, 1, 1, tzinfo=timezone.utc), synthetic()),
                             "UST_REAL_10Y", 20, "rise", 50.0, "USDKRW", 20)


def accepted_memo(ctx: ToolContext) -> tuple[dict, set]:
    latest = get_latest(ctx, "USDKRW", 1)["observations"][0]["evidence_id"]
    change = get_change(ctx, "UST_REAL_10Y", 20)
    cond = conditional_outcomes(ctx, "UST_REAL_10Y", 20, "rise", 0.1, "USDKRW", 20)
    ep, base = cond["episodes"], cond["all_days_baseline"]
    memo = {"title": "실질금리와 원/달러",
            "sentences": [
                {"text": "원/달러는 {{date:" + latest + "}} 기준 {{ev:" + latest + "}}였습니다.",
                 "kind": "fact", "evidence_ids": [latest]},
                {"text": "미국 실질금리는 최근 20개 관측 동안 {{ev:" + change["evidence_id"] + "}} 상승했습니다.",
                 "kind": "fact", "evidence_ids": [change["evidence_id"]]},
                {"text": "과거 비슷한 상승 뒤 20거래일 원/달러 상승 비율은 {{ev:" + ep["share_up"]["evidence_id"]
                         + "}}로 전체 기간 {{ev:" + base["share_up"]["evidence_id"] + "}}보다 높았습니다.",
                 "kind": "interpretation",
                 "evidence_ids": [ep["share_up"]["evidence_id"], base["share_up"]["evidence_id"]]},
                {"text": "이는 과거의 연관성이며 인과 효과가 아닙니다.", "kind": "caveat", "evidence_ids": []}],
            "cannot_say": ["향후 원/달러 수준은 이 도구로 예측하지 않습니다."]}
    return memo, allowed_numbers("질문", [{"window": 20, "horizon": 20, "threshold": 0.1, "count": 1}])


def test_clean_memo_passes_and_renders_numbers_from_evidence():
    data = synthetic()
    ctx = ToolContext(data["USDKRW"][700].available_utc, data)
    memo, allowed = accepted_memo(ctx)
    assert verify(memo, ctx.registry.items, ctx.as_of_utc, allowed) == []
    text = render(memo, ctx.registry.items, ctx.as_of_utc, "질문", {"violations": []})
    assert "{{" not in text and "원" in text and "| 1 |" in text


def test_every_rule_mutation_is_caught():
    data = synthetic()
    ctx = ToolContext(data["USDKRW"][700].available_utc, data)
    memo, allowed = accepted_memo(ctx)
    seen = set()
    for name, _, mutant, registry in rule_mutants(memo, ctx.registry.items, data, ctx.as_of_utc):
        codes = {v["code"] for v in verify(mutant, registry, ctx.as_of_utc, allowed)}
        assert RULE_EXPECTED[name] in codes, (name, codes)
        seen.add(name)
    assert seen == set(RULE_EXPECTED)
    assert any(True for _ in meaning_mutants(memo))


def response(*blocks, stop="tool_use"):
    usage = SimpleNamespace(input_tokens=100, output_tokens=20, cache_read_input_tokens=0)
    return SimpleNamespace(content=list(blocks), stop_reason=stop, model="claude-opus-5-5", usage=usage)


def use(id_, name, args):
    return SimpleNamespace(type="tool_use", id=id_, name=name, input=args)


class FakeClient:
    def __init__(self, script):
        self.script, self.requests = list(script), []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        return self.script.pop(0)


def test_loop_repairs_a_typed_number_then_accepts_and_judges():
    data = synthetic()
    as_of = data["USDKRW"][700].available_utc
    latest_obs = [o for o in data["USDKRW"] if o.available_utc <= as_of][-1]
    eid = f"obs:USDKRW:{latest_obs.obs_date.isoformat()}"
    bad = {"title": "원/달러", "cannot_say": [],
           "sentences": [{"text": "원/달러는 1,234.56원입니다.", "kind": "fact", "evidence_ids": [eid]}]}
    good = {"title": "원/달러", "cannot_say": [],
            "sentences": [{"text": "원/달러는 {{ev:" + eid + "}}입니다.", "kind": "fact", "evidence_ids": [eid]}]}
    verdict = json.dumps({"results": [{"index": 0, "verdict": "supported", "reason": "값과 일치"}]})
    client = FakeClient([
        response(use("t1", "list_series", {})),
        response(use("t2", "get_latest", {"series_id": "USDKRW", "count": 1})),
        response(use("t3", "submit_memo", bad)),
        response(use("t4", "submit_memo", good)),
        response(SimpleNamespace(type="text", text=verdict), stop="end_turn"),
    ])
    record = run("원/달러 현황은?", as_of, data, client)
    assert record["status"] == "accepted"
    assert record["verification"]["repairs"] == 1 and record["verification"]["violations"] == []
    assert record["submissions"][0]["violations"][0]["code"] == "typed_number"
    assert record["audit"]["after_as_of"] == []
    assert f"{latest_obs.value:,.2f}원" in record["markdown"]
    assert "1문장 중 1문장" in record["verification"]["semantic_summary"]
    sent = client.requests[0]
    assert sent["fallbacks"] == "default" and sent["thinking"] == {"type": "adaptive"}
    assert "tool_choice" not in sent


def test_snapshot_tampering_is_detected(tmp_path):
    folder = sources._publish("h10_krw", {"dat00_ko.htm": ("u", b'<th id="r1"> 3-JAN-00 </th><td>1.0</td>')},
                              tmp_path)
    tsy = sources._publish("treasury", {"real_2003.csv": ("u", b'Date,"10 YR"\n01/02/2003,2.0\n')}, tmp_path)
    assert sources.load_observations(tmp_path)["UST_REAL_10Y"][0].value == 2.0
    (tsy / "real_2003.csv").write_bytes(b'Date,"10 YR"\n01/02/2003,9.9\n')
    with pytest.raises(ValueError, match="changed after publication"):
        sources.load_observations(tmp_path)
    assert folder.exists() and not any(p.name.endswith(".partial") for p in (tmp_path / "h10_krw").iterdir())
