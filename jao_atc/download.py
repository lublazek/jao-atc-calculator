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


class NotPublishedError(LookupError):
    """The requested IDCC run has no data (yet) for the requested day."""


def dataset_name(run: str) -> str:
    run = run.upper()
    if run not in RUNS:
        raise ValueError(f'Unknown IDCC run {run!r}; expected one of {", ".join(RUNS)}')
    return f'IDCC{run}_intradayAtc'


def _delivery_day(day=None, tz: str = TZ) -> pd.Timestamp:
    """Midnight (local time) of the delivery day. Default: today."""
    if day is None:
        return pd.Timestamp.now(tz=tz).normalize()
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


def fetch_run(run: str = 'D', day=None, tz: str = TZ,
              session: requests.Session | None = None) -> pd.DataFrame:
    """Fetch one IDCC run for one delivery day.

    Raises NotPublishedError if the run returned no rows.
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
    if not rows:
        raise NotPublishedError(f'IDCC({run.lower()}) not published for {start.date()}')
    return _to_frame(rows, tz)


def fetch_all(day=None, runs=RUNS, tz: str = TZ, verbose: bool = True) -> dict[str, pd.DataFrame]:
    """Fetch several IDCC runs for one day. Runs without data are skipped."""
    out: dict[str, pd.DataFrame] = {}
    with requests.Session() as s:
        for run in runs:
            run = run.upper()
            try:
                out[run] = fetch_run(run, day, tz, session=s)
                if verbose:
                    df = out[run]
                    print(f'IDCC({run.lower()}): {len(df)} MTUs, {df.shape[1]} borders, '
                          f'{df.index.min():%Y-%m-%d %H:%M} -> {df.index.max():%H:%M}')
            except NotPublishedError as e:
                if verbose:
                    print(f'IDCC({run.lower()}): skipped - {e}')
    return out


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
    p.add_argument('--day', help='Delivery day YYYY-MM-DD (default: today)')
    p.add_argument('--runs', default=''.join(RUNS), help='Runs to fetch, e.g. ABCDE or D')
    p.add_argument('--out', default='data', help='Output folder (default: data/)')
    a = p.parse_args(argv)
    dfs = fetch_all(a.day, runs=a.runs)
    for path in save(dfs, a.day, a.out):
        print(f'saved {path}')


if __name__ == '__main__':
    main()
