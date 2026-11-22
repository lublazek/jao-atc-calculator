import pandas as pd
import pytest

from jao_atc import download as dl

ROWS = [
    {'dateTimeUtc': '2026-11-20T23:15:00Z', 'border_CZ_SK': 500, 'border_SK_CZ': -20, 'id': 2},
    {'dateTimeUtc': '2026-11-20T23:00:00Z', 'border_CZ_SK': 400, 'border_SK_CZ': 100, 'id': 1},
]


class FakeResp:
    def __init__(self, rows): self.rows = rows
    def raise_for_status(self): pass
    def json(self): return {'data': self.rows}


class FakeSession:
    def __init__(self, by_dataset): self.by_dataset, self.calls = by_dataset, []
    def get(self, url, params, timeout):
        self.calls.append((url, params))
        return FakeResp(self.by_dataset.get(url.rsplit('/', 1)[1], []))
    def __enter__(self): return self
    def __exit__(self, *a): pass


def test_fetch_run_parses_and_requests_local_day():
    s = FakeSession({'IDCCD_intradayAtc': ROWS})
    df = dl.fetch_run('d', '2026-11-21', session=s)
    assert list(df.columns) == ['CZ>SK', 'SK>CZ']
    assert df.index[0] == pd.Timestamp('2026-11-21 00:00', tz=dl.TZ)   # sorted, local time
    assert df.iloc[0]['CZ>SK'] == 400
    assert s.calls[0][1] == {'FromUtc': '2026-11-20T23:00:00.000Z', 'ToUtc': '2026-11-21T23:00:00.000Z'}


def test_dst_day_is_25h():
    s = FakeSession({'IDCCA_intradayAtc': ROWS})
    dl.fetch_run('A', '2026-10-25', session=s)
    assert s.calls[0][1] == {'FromUtc': '2026-10-24T22:00:00.000Z', 'ToUtc': '2026-10-25T23:00:00.000Z'}


def test_not_published_raises():
    with pytest.raises(dl.NotPublishedError):
        dl.fetch_run('E', '2026-11-21', session=FakeSession({}))


def test_unknown_run():
    with pytest.raises(ValueError):
        dl.dataset_name('F')


def test_fetch_all_skips_missing(monkeypatch):
    s = FakeSession({'IDCCA_intradayAtc': ROWS, 'IDCCC_intradayAtc': ROWS})
    monkeypatch.setattr(dl.requests, 'Session', lambda: s)
    dfs = dl.fetch_all('2026-11-21', verbose=False)
    assert sorted(dfs) == ['A', 'C']


def test_save_load_roundtrip(tmp_path):
    df = dl.fetch_run('B', '2026-11-21', session=FakeSession({'IDCCB_intradayAtc': ROWS}))
    dl.save({'B': df}, '2026-11-21', tmp_path)
    back = dl.load('B', '2026-11-21', tmp_path)
    pd.testing.assert_frame_equal(df, back, check_freq=False, check_dtype=False, check_names=False)


def test_spring_dst_day_is_23h():
    s = FakeSession({})
    with pytest.raises(dl.NotPublishedError):
        dl.fetch_run('A', '2026-03-29', session=s)
    assert s.calls[0][1] == {'FromUtc': '2026-03-28T23:00:00.000Z', 'ToUtc': '2026-03-29T22:00:00.000Z'}
