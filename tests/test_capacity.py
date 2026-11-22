import pandas as pd
import pytest

from jao_atc import capacity as cap

# CZ -> HU has no direct border: two parallel routes via SK and via AT.
ATC = pd.Series({
    'CZ>SK': 300, 'SK>HU': 500,     # route 1 limited to 300
    'CZ>AT': 400, 'AT>HU': 200,     # route 2 limited to 200
    'HU>SK': 100, 'SK>CZ': -50,     # negative ATC -> 0
})


def test_parallel_paths_add_up():
    assert cap.max_flow(ATC, 'CZ', 'HU') == 500          # old method (best single path) gave 300


def test_negative_atc_is_zero():
    assert cap.max_flow(ATC, 'HU', 'CZ') == 0


def test_shared_border_is_not_double_counted():
    # Both routes DE->SK must use CZ>SK, so its 300 MW is the limit.
    atc = pd.Series({'DE>CZ': 1000, 'DE>PL': 1000, 'PL>CZ': 1000, 'CZ>SK': 300})
    assert cap.max_flow(atc, 'DE', 'SK') == 300


def test_paths_breakdown():
    assert cap.max_flow_paths(ATC, 'CZ', 'HU') == {'CZ>SK': 300, 'SK>HU': 300, 'CZ>AT': 200, 'AT>HU': 200}


def test_all_pairs_matches_single_and_covers_every_pair():
    df = pd.DataFrame([ATC, ATC * 2], index=pd.date_range('2026-11-22', periods=2, freq='15min'))
    out = cap.all_pairs(df)
    zs = cap.zones(df)
    assert out.shape == (2, len(zs) * (len(zs) - 1))
    assert list(out['CZ>HU']) == [500, 1000]


def test_never_below_direct_border():
    out = cap.all_pairs(pd.DataFrame([ATC]))
    for border, v in ATC.items():
        assert out.iloc[0][border] >= max(v, 0)


def test_run_column_is_ignored():
    df = pd.DataFrame([ATC]).assign(run='E')
    assert cap.zones(df) == ['AT', 'CZ', 'HU', 'SK']
    assert cap.all_pairs(df).iloc[0]['CZ>HU'] == 500
    assert cap.max_flow(df.iloc[0], 'CZ', 'HU') == 500


def test_unknown_zone_gives_clear_error():
    with pytest.raises(ValueError, match='XX'):
        cap.max_flow(ATC, 'CZ', 'XX')
    with pytest.raises(ValueError, match='XX'):
        cap.all_pairs(pd.DataFrame([ATC]), pairs=[('CZ', 'XX')])


def test_hourly_is_min_of_quarter_hours_even_if_routes_change():
    # Quarter 1 can only route via SK, quarter 2 only via AT: each still carries 100.
    q1 = {'CZ>SK': 100, 'SK>HU': 100, 'CZ>AT': 0, 'AT>HU': 0}
    q2 = {'CZ>SK': 0, 'SK>HU': 0, 'CZ>AT': 100, 'AT>HU': 100}
    q3 = {'CZ>SK': 300, 'SK>HU': 300, 'CZ>AT': 0, 'AT>HU': 0}
    idx = pd.date_range('2026-11-22', periods=4, freq='15min', tz='Europe/Luxembourg')
    flow = cap.all_pairs(pd.DataFrame([q1, q2, q3, q3], index=idx), pairs=[('CZ', 'HU')])
    assert cap.hourly(flow)['CZ>HU'].tolist() == [100]
