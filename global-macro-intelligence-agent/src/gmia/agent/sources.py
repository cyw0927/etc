"""Official no-key sources for the research agent: raw bytes kept immutable, then parsed.

Availability times are conservative rules written per source, not observed publication times.
Only series that the publisher does not revise are used, so a current snapshot can answer a past as-of.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import time as _time
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

ET = ZoneInfo("America/New_York")
USER_AGENT = "gmia-research-agent (personal research prototype)"
PROJECT_ROOT = Path(__file__).resolve().parents[3]
SNAPSHOT_ROOT = PROJECT_ROOT / "data" / "agent" / "snapshots"

TREASURY_CSV = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
                "daily-treasury-rates.csv/{year}/all?type={kind}&field_tdr_date_value={year}&page&_format=csv")
H10_KRW = "https://www.federalreserve.gov/releases/h10/hist/dat00_ko.htm"


@dataclass(frozen=True)
class SeriesSpec:
    series_id: str
    label: str
    unit: str
    change_unit: str  # "pp" for rates (difference), "pct" for prices (percent change)
    source: str
    page_url: str
    availability_rule: str


SERIES = {
    "UST_REAL_10Y": SeriesSpec(
        "UST_REAL_10Y", "미국 10년 실질금리(TIPS par yield)", "%", "pp", "U.S. Treasury",
        "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
        "TextView?type=daily_treasury_real_yield_curve",
        "관측일 다음 날 06:00 ET 이후 사용(보수적 가정)"),
    "UST_NOM_10Y": SeriesSpec(
        "UST_NOM_10Y", "미국 10년 국채금리(par yield)", "%", "pp", "U.S. Treasury",
        "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
        "TextView?type=daily_treasury_yield_curve",
        "관측일 다음 날 06:00 ET 이후 사용(보수적 가정)"),
    "USDKRW": SeriesSpec(
        "USDKRW", "원/달러 환율(뉴욕 정오 매입률, 1달러당 원)", "원", "pct", "Federal Reserve H.10",
        H10_KRW,
        "H.10은 매주 월요일 16:15 ET에 지난주 값을 공개. 휴일 여유를 두어 관측 주 다음 화요일 17:00 ET 이후 사용"),
}


@dataclass(frozen=True)
class Observation:
    series_id: str
    obs_date: date
    value: float
    available_utc: datetime
    file_sha256: str
    snapshot: str


def available_utc(series_id: str, obs_date: date) -> datetime:
    """When a value may be used, by the conservative rule in SERIES[series_id].availability_rule."""
    if series_id in ("UST_REAL_10Y", "UST_NOM_10Y"):
        local = datetime.combine(obs_date + timedelta(days=1), time(6, 0), ET)
    elif series_id == "USDKRW":
        monday = obs_date - timedelta(days=obs_date.weekday())
        local = datetime.combine(monday + timedelta(days=8), time(17, 0), ET)
    else:
        raise KeyError(series_id)
    return local.astimezone(timezone.utc)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _get(url: str) -> bytes:
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=60)
    response.raise_for_status()
    return response.content


def _publish(source_key: str, files: dict[str, tuple[str, bytes]], root: Path) -> Path:
    """Write raw files and a manifest into a hidden .partial folder, then rename: never a half snapshot."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name = f"{stamp}-{uuid.uuid4().hex[:10]}"
    folder = root / source_key / f".{name}.partial"
    folder.mkdir(parents=True, exist_ok=False)
    manifest = {"source_key": source_key, "created_utc": datetime.now(timezone.utc).isoformat(), "files": {}}
    for filename, (url, raw) in files.items():
        with (folder / filename).open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        manifest["files"][filename] = {"url": url, "sha256": _sha(raw), "bytes": len(raw)}
    with (folder / "manifest.json").open("x", encoding="utf-8") as stream:
        json.dump(manifest, stream, indent=2, ensure_ascii=False)
    final = root / source_key / name
    folder.rename(final)
    return final


def fetch_treasury(first_year: int, last_year: int, root: Path = SNAPSHOT_ROOT, pause: float = 0.5) -> Path:
    files = {}
    for kind, prefix in (("daily_treasury_real_yield_curve", "real"), ("daily_treasury_yield_curve", "nominal")):
        for year in range(first_year, last_year + 1):
            url = TREASURY_CSV.format(year=year, kind=kind)
            files[f"{prefix}_{year}.csv"] = (url, _get(url))
            _time.sleep(pause)
    return _publish("treasury", files, root)


def fetch_h10_krw(root: Path = SNAPSHOT_ROOT) -> Path:
    return _publish("h10_krw", {"dat00_ko.htm": (H10_KRW, _get(H10_KRW))}, root)


def parse_treasury_csv(raw: bytes, column: str) -> list[tuple[date, float]]:
    """Rows of (date, value) for one tenor column; header case differs between real and nominal files."""
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    wanted = next((name for name in (reader.fieldnames or []) if name.strip().lower() == column.lower()), None)
    if wanted is None:
        return []
    rows = []
    for row in reader:
        text = (row.get(wanted) or "").strip()
        if not text or text.upper() in ("N/A", "ND"):
            continue
        rows.append((datetime.strptime(row["Date"], "%m/%d/%Y").date(), float(text)))
    return rows


_H10_ROW = re.compile(r'<th id="r1"[^>]*>\s*([0-9]{1,2}-[A-Z]{3}-[0-9]{2})\s*</th>\s*<td[^>]*>\s*([^<]*?)\s*</td>', re.S)


def parse_h10(raw: bytes) -> list[tuple[date, float]]:
    """H.10 historical table; "ND" (no data, e.g. holidays) rows are skipped, never filled."""
    rows = []
    for day, text in _H10_ROW.findall(raw.decode("utf-8", errors="replace")):
        if text.upper() == "ND" or not text:
            continue
        rows.append((datetime.strptime(day, "%d-%b-%y").date(), float(text)))
    return rows


def _latest(source_key: str, root: Path) -> Path:
    folders = sorted(p for p in (root / source_key).glob("*") if p.is_dir() and not p.name.startswith("."))
    if not folders:
        raise FileNotFoundError(f"no {source_key} snapshot under {root}; run the fetch first")
    return folders[-1]


def _verified_files(folder: Path) -> dict[str, tuple[bytes, str]]:
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    out = {}
    for filename, meta in manifest["files"].items():
        raw = (folder / filename).read_bytes()
        if _sha(raw) != meta["sha256"]:
            raise ValueError(f"snapshot file changed after publication: {folder.name}/{filename}")
        out[filename] = (raw, meta["sha256"])
    return out


def load_observations(root: Path = SNAPSHOT_ROOT) -> dict[str, list[Observation]]:
    """All series from the latest verified snapshot of each source, sorted by observation date."""
    series: dict[str, list[Observation]] = {key: [] for key in SERIES}
    treasury = _latest("treasury", root)
    for filename, (raw, sha) in sorted(_verified_files(treasury).items()):
        target = "UST_REAL_10Y" if filename.startswith("real_") else "UST_NOM_10Y"
        column = "10 YR" if target == "UST_REAL_10Y" else "10 Yr"
        for day, value in parse_treasury_csv(raw, column):
            series[target].append(Observation(target, day, value, available_utc(target, day), sha, treasury.name))
    h10 = _latest("h10_krw", root)
    for _, (raw, sha) in _verified_files(h10).items():
        for day, value in parse_h10(raw):
            series["USDKRW"].append(Observation("USDKRW", day, value, available_utc("USDKRW", day), sha, h10.name))
    for key, rows in series.items():
        rows.sort(key=lambda o: o.obs_date)
        days = [o.obs_date for o in rows]
        if len(days) != len(set(days)):
            raise ValueError(f"duplicate observation dates in {key}")
    return series
