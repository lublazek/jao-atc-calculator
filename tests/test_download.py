import pandas as pd
import pytest
import requests

from jao_atc import download as dl

# Most fixtures hold only a few MTUs; the completeness warning is tested on its own.
pytestmark = pytest.mark.filterwarnings('ignore:IDCC.*MTU')

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
    df = dl.fetch_run('d', '2026-11-21', trim=False, session=s)
    assert list(df.columns) == ['CZ>SK', 'SK>CZ']
    assert df.index[0] == pd.Timestamp('2026-11-21 00:00', tz=dl.TZ)   # sorted, local time
    assert df.iloc[0]['CZ>SK'] == 400
    assert s.calls[0][1] == {'FromUtc': '2026-11-20T23:00:00.000Z', 'ToUtc': '2026-11-21T23:00:00.000Z'}


def test_dst_day_is_25h():
    s = FakeSession({})
    with pytest.raises(dl.NotPublishedError):
        dl.fetch_run('A', '2026-10-25', session=s)
    assert s.calls[0][1] == {'FromUtc': '2026-10-24T22:00:00.000Z', 'ToUtc': '2026-10-25T23:00:00.000Z'}


def test_not_published_raises():
    with pytest.raises(dl.NotPublishedError):
        dl.fetch_run('E', '2026-11-21', session=FakeSession({}))


def test_unknown_run():
    with pytest.raises(ValueError):
        dl.dataset_name('F')


def test_fetch_all_skips_missing(monkeypatch):
    s = FakeSession({'IDCCA_intradayAtc': ROWS, 'IDCCC_intradayAtc': ROWS})  # C rows are before 06:00
    monkeypatch.setattr(dl.requests, 'Session', lambda: s)
    dfs = dl.fetch_all('2026-11-21', verbose=False)
    assert sorted(dfs) == ['A']   # C trimmed to nothing -> skipped
    assert sorted(dl.fetch_all('2026-11-21', trim=False, verbose=False)) == ['A', 'C']


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


def _rows(*local_times, value=100):
    return [{'dateTimeUtc': pd.Timestamp(f'2026-11-21 {t}', tz=dl.TZ).tz_convert('UTC').isoformat(),
             'border_CZ_SK': value} for t in local_times]


@pytest.mark.parametrize('run,first', [('A', '00:00'), ('B', '00:00'), ('C', '06:00'), ('D', '12:00'), ('E', '18:00')])
def test_trim_to_coverage(run, first):
    rows = _rows('00:00', '05:45', '06:00', '11:45', '12:00', '17:45', '18:00', '23:45')
    df = dl.fetch_run(run, '2026-11-21', session=FakeSession({dl.dataset_name(run): rows}))
    assert df.index[0] == pd.Timestamp(f'2026-11-21 {first}', tz=dl.TZ)
    assert df.index[-1] == pd.Timestamp('2026-11-21 23:45', tz=dl.TZ)


def test_only_uncovered_rows_counts_as_not_published():
    with pytest.raises(dl.NotPublishedError):
        dl.fetch_run('E', '2026-11-21', session=FakeSession({'IDCCE_intradayAtc': _rows('10:00')}))


def test_latest_takes_newest_run_per_mtu():
    dfs = {
        'B': dl._to_frame(_rows('00:00', '06:00', '12:00', '18:00', value=1), dl.TZ),
        'C': dl._to_frame(_rows('06:00', '12:00', '18:00', value=3), dl.TZ),
        'E': dl._to_frame(_rows('18:00', value=5), dl.TZ),
    }
    out = dl.latest(dfs)
    assert list(out['run']) == ['B', 'C', 'C', 'E']
    assert list(out['CZ>SK']) == [1, 3, 3, 5]


def test_select():
    dfs = {'A': dl._to_frame(_rows('00:00'), dl.TZ)}
    assert dl.select(dfs, 'a') is dfs['A']
    assert 'run' in dl.select(dfs, 'latest')
    with pytest.raises(dl.NotPublishedError, match='published runs: A'):
        dl.select(dfs, 'D')


def test_tomorrow():
    today = pd.Timestamp.now(tz=dl.TZ).normalize()
    assert dl._delivery_day('tomorrow') == (today + pd.DateOffset(days=1)).normalize()
    assert dl._delivery_day('today') == today


# --- robustness ---------------------------------------------------------------

def _full_day(day, value=100, extra=()):
    start = pd.Timestamp(day, tz=dl.TZ)
    idx = dl._expected_mtus(start, start + pd.DateOffset(days=1))
    return [{'dateTimeUtc': t.tz_convert('UTC').isoformat(), 'border_CZ_SK': value} for t in idx] + list(extra)


@pytest.mark.parametrize('day,n', [('2026-11-21', 96), ('2026-03-29', 92), ('2026-10-25', 100)])
def test_complete_day_has_no_warning(day, n, recwarn):
    df = dl.fetch_run('A', day, session=FakeSession({'IDCCA_intradayAtc': _full_day(day)}))
    assert len(df) == n
    assert not [w for w in recwarn if 'missing' in str(w.message)]


def test_missing_mtus_warn():
    rows = _full_day('2026-11-21')[:-4]
    with pytest.warns(UserWarning, match='4 MTU'):
        dl.fetch_run('A', '2026-11-21', session=FakeSession({'IDCCA_intradayAtc': rows}))


def test_rows_outside_day_and_duplicates_are_dropped():
    other_day = {'dateTimeUtc': '2026-11-22T23:00:00Z', 'border_CZ_SK': 1}
    dup = dict(_full_day('2026-11-21')[0], border_CZ_SK=999)
    rows = _full_day('2026-11-21', extra=[other_day, dup])
    df = dl.fetch_run('A', '2026-11-21', session=FakeSession({'IDCCA_intradayAtc': rows}))
    assert len(df) == 96
    assert df.index.is_unique
    assert df['CZ>SK'].iloc[0] == 999                 # last duplicate wins


def test_fetch_all_survives_http_error(monkeypatch):
    class Flaky(FakeSession):
        def get(self, url, params, timeout):
            if 'IDCCE' in url:
                raise requests.ConnectionError('timeout')
            return super().get(url, params, timeout)
    s = Flaky({'IDCCA_intradayAtc': ROWS})
    monkeypatch.setattr(dl.requests, 'Session', lambda: s)
    assert sorted(dl.fetch_all('2026-11-21', verbose=False)) == ['A']


def test_latest_ignores_rows_outside_coverage():
    dfs = {'B': dl._to_frame(_rows('00:00', '18:00', value=1), dl.TZ),
           'E': dl._to_frame(_rows('00:00', '18:00', value=5), dl.TZ)}     # untrimmed E
    out = dl.latest(dfs)
    assert list(out['run']) == ['B', 'E']
    assert list(out['CZ>SK']) == [1, 5]


def test_latest_fills_gap_from_older_run_and_warns():
    dfs = {'B': dl._to_frame(_rows('18:00', '18:15', '18:30', value=1), dl.TZ),
           'E': dl._to_frame(_rows('18:00', '18:30', value=5), dl.TZ)}     # E misses 18:15
    with pytest.warns(UserWarning, match='1 MTU'):
        out = dl.latest(dfs)
    assert list(out['run']) == ['E', 'B', 'E']
    assert list(out['CZ>SK']) == [5, 1, 5]


def test_latest_fills_missing_border_from_older_run_and_warns():
    b = dl._to_frame(_rows('18:00', value=1), dl.TZ).assign(**{'SK>CZ': 7})
    e = dl._to_frame(_rows('18:00', value=5), dl.TZ)                       # no SK>CZ column
    with pytest.warns(UserWarning, match='SK>CZ'):
        out = dl.latest({'B': b, 'E': e})
    assert out.iloc[0]['CZ>SK'] == 5 and out.iloc[0]['SK>CZ'] == 7


def test_save_load_latest(tmp_path):
    dfs = {'B': dl._to_frame(_rows('00:00', value=1), dl.TZ)}
    dl.save({'latest': dl.latest(dfs)}, '2026-11-21', tmp_path)
    back = dl.load('latest', '2026-11-21', tmp_path)
    assert list(back['run']) == ['B']
