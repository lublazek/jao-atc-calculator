"""Download Core intraday ATCs (IDCC runs a-e) from the JAO publication tool.

Each IDCC run is published as its own dataset, ``IDCC{RUN}_intradayAtc``.
The result for one run is a DataFrame indexed by MTU (local time) with one
column per directed border, named ``FROM>TO`` (e.g. ``CZ>SK``).

Usage from Python::

    from jao_atc.download import fetch_run, fetch_all
    df  = fetch_run('D')                 # today, IDCC(d)
    dfs = fetch_all('2026-11-21')        # {'A': df, 'B': df, ...}, unpublished runs skipped

Usage from the command line (saves CSVs to ``data/``)::

    python -m jao_atc.download --day 2026-11-21 --runs ABCDE
    python -m jao_atc.download --day tomorrow --runs AB

Run timing (delivery day D, local time) is in RUN_INFO: IDCC(a) at D-1 15:00
and IDCC(b) at D-1 22:00 cover the whole of D; IDCC(c) at 04:00 for 06:00 onwards,
IDCC(d) at 10:00 for 12:00 onwards, IDCC(e) at 16:00 for 18:00 onwards.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
import requests

TZ = 'Europe/Luxembourg'
BASE_URL = 'https://publicationtool.jao.eu/coreID/api/data'
RUNS = ('A', 'B', 'C', 'D', 'E')
TIMEOUT = 60

# When each run is calculated and from which MTU of delivery day D it applies
# (local time). IDCC(a)/(b) are calculated on D-1 and cover the whole of D;
# IDCC(c)/(d)/(e) are calculated on D itself and cover the rest of the day.
RUN_INFO = {
    'A': {'calc_day': 'D-1', 'calc_time': '15:00', 'from': '00:00'},
    'B': {'calc_day': 'D-1', 'calc_time': '22:00', 'from': '00:00'},
    'C': {'calc_day': 'D',   'calc_time': '04:00', 'from': '06:00'},
    'D': {'calc_day': 'D',   'calc_time': '10:00', 'from': '12:00'},
    'E': {'calc_day': 'D',   'calc_time': '16:00', 'from': '18:00'},
}


class NotPublishedError(LookupError):
    """The requested IDCC run has no data (yet) for the requested day."""


def dataset_name(run: str) -> str:
    run = run.upper()
    if run not in RUNS:
        raise ValueError(f'Unknown IDCC run {run!r}; expected one of {", ".join(RUNS)}')
    return f'IDCC{run}_intradayAtc'


def _delivery_day(day=None, tz: str = TZ) -> pd.Timestamp:
    """Midnight (local time) of the delivery day.

    ``day`` may be None / 'today', 'tomorrow', or anything pd.Timestamp accepts.
    """
    if day is None or (isinstance(day, str) and day.lower() == 'today'):
        return pd.Timestamp.now(tz=tz).normalize()
    if isinstance(day, str) and day.lower() == 'tomorrow':
        return (pd.Timestamp.now(tz=tz).normalize() + pd.DateOffset(days=1)).normalize()
    ts = pd.Timestamp(day)
    ts = ts.tz_localize(tz) if ts.tzinfo is None else ts.tz_convert(tz)
    return ts.normalize()


def _utc(ts: pd.Timestamp) -> str:
    return ts.tz_convert('UTC').strftime('%Y-%m-%dT%H:%M:%S.000Z')


def _to_frame(rows: list[dict], tz: str) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    df['mtu'] = pd.to_datetime(df['dateTimeUtc'], utc=True).dt.tz_convert(tz)
    df = df.set_index('mtu').sort_index()
    df = df[[c for c in df.columns if c.startswith('border_')]]
    df.columns = [c.removeprefix('border_').replace('_', '>') for c in df.columns]
    return df.apply(pd.to_numeric, errors='coerce')


def coverage_start(run: str, day=None, tz: str = TZ) -> pd.Timestamp:
    """First MTU (local time) of delivery day ``day`` that ``run`` applies to."""
    h, m = map(int, RUN_INFO[run.upper()]['from'].split(':'))
    return _delivery_day(day, tz).replace(hour=h, minute=m)


def fetch_run(run: str = 'D', day=None, tz: str = TZ, trim: bool = True,
              session: requests.Session | None = None) -> pd.DataFrame:
    """Fetch one IDCC run for one delivery day.

    With ``trim`` (default) only the MTUs the run covers are kept, e.g.
    IDCC(d) from 12:00. Raises NotPublishedError if nothing is left.
    """
    start = _delivery_day(day, tz)
    end = start + pd.DateOffset(days=1)         # calendar day: 23h/25h on DST switch days
    http = session or requests
    r = http.get(
        f'{BASE_URL}/{dataset_name(run)}',
        params={'FromUtc': _utc(start), 'ToUtc': _utc(end)},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    rows = r.json().get('data', [])
    df = _to_frame(rows, tz) if rows else pd.DataFrame()
    if trim and not df.empty:
        df = df[df.index >= coverage_start(run, start, tz)]
    if df.empty:
        raise NotPublishedError(f'IDCC({run.lower()}) not published for {start.date()}')
    return df


def fetch_all(day=None, runs=RUNS, tz: str = TZ, trim: bool = True,
              verbose: bool = True) -> dict[str, pd.DataFrame]:
    """Fetch several IDCC runs for one day. Runs without data are skipped."""
    out: dict[str, pd.DataFrame] = {}
    with requests.Session() as s:
        for run in runs:
            run = run.upper()
            try:
                out[run] = fetch_run(run, day, tz, trim=trim, session=s)
                if verbose:
                    df = out[run]
                    print(f'IDCC({run.lower()}): {len(df)} MTUs, {df.shape[1]} borders, '
                          f'{df.index.min():%Y-%m-%d %H:%M} -> {df.index.max():%H:%M}')
            except NotPublishedError as e:
                if verbose:
                    print(f'IDCC({run.lower()}): skipped - {e}')
    return out


def latest(dfs: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Combine runs: for every MTU take the values of the newest run covering it.

    Adds a ``run`` column saying which IDCC run each row comes from.
    """
    if not dfs:
        raise NotPublishedError('No IDCC run available')
    parts = []
    for run in sorted(dfs):                       # A..E = oldest..newest
        parts.append(dfs[run].assign(run=run))
    combined = pd.concat(parts)
    return combined[~combined.index.duplicated(keep='last')].sort_index()


def select(dfs: dict[str, pd.DataFrame], run: str) -> pd.DataFrame:
    """Pick one run from fetch_all() output, or 'latest' for the combination."""
    if run.lower() == 'latest':
        return latest(dfs)
    run = run.upper()
    if run not in dfs:
        avail = ', '.join(sorted(dfs)) or 'none'
        raise NotPublishedError(f'IDCC({run.lower()}) not available - published runs: {avail}')
    return dfs[run]


def save(dfs: dict[str, pd.DataFrame], day=None, folder: str | Path = 'data', tz: str = TZ) -> list[Path]:
    """Save each run as data/IDCC{run}_{YYYY-MM-DD}.csv."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    d = _delivery_day(day, tz).date()
    paths = []
    for run, df in dfs.items():
        p = folder / f'IDCC{run}_{d}.csv'
        df.to_csv(p)
        paths.append(p)
    return paths


def load(run: str, day=None, folder: str | Path = 'data', tz: str = TZ) -> pd.DataFrame:
    """Load a run previously saved with save()."""
    d = _delivery_day(day, tz).date()
    df = pd.read_csv(Path(folder) / f'IDCC{run.upper()}_{d}.csv', index_col='mtu')
    df.index = pd.to_datetime(df.index, utc=True).tz_convert(tz)
    return df


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description='Download JAO Core IDCC ATCs.')
    p.add_argument('--day', help="Delivery day YYYY-MM-DD, 'today' (default) or 'tomorrow'")
    p.add_argument('--runs', default=''.join(RUNS), help='Runs to fetch, e.g. ABCDE or D')
    p.add_argument('--out', default='data', help='Output folder (default: data/)')
    a = p.parse_args(argv)
    dfs = fetch_all(a.day, runs=a.runs)
    for path in save(dfs, a.day, a.out):
        print(f'saved {path}')


if __name__ == '__main__':
    main()
