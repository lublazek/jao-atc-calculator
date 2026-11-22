"""Cross-zonal capacity between any two bidding zones, as max-flow over border ATCs."""
from __future__ import annotations

import networkx as nx
import pandas as pd


def borders(cols) -> list[str]:
    """Border columns ('CZ>SK', ...); other columns such as 'run' are ignored."""
    return [c for c in cols if '>' in c]


def zones(df: pd.DataFrame) -> list[str]:
    """Bidding zones appearing in the border columns."""
    return sorted({z for col in borders(df.columns) for z in col.split('>')})


def build_graph(atc: pd.Series) -> nx.DiGraph:
    """One MTU of border ATCs -> directed graph. Negative or missing ATC counts as 0."""
    g = nx.DiGraph()
    for border in borders(atc.index):
        value = atc[border]
        src, dst = border.split('>')
        g.add_edge(src, dst, capacity=max(float(value), 0.0) if pd.notna(value) else 0.0)
    return g


def _check_zones(available, wanted) -> None:
    unknown = sorted(set(wanted) - set(available))
    if unknown:
        raise ValueError(f'Zone(s) {", ".join(unknown)} not in data; available: {", ".join(sorted(available))}')


def max_flow(atc: pd.Series, src: str, dst: str) -> float:
    """Maximum MW that can flow from src to dst in one MTU, using all paths at once."""
    g = build_graph(atc)
    _check_zones(g.nodes, (src, dst))
    return nx.maximum_flow_value(g, src, dst)


def max_flow_paths(atc: pd.Series, src: str, dst: str) -> dict[str, float]:
    """How the max-flow from src to dst is split over the borders (only borders with flow)."""
    g = build_graph(atc)
    _check_zones(g.nodes, (src, dst))
    _, flow = nx.maximum_flow(g, src, dst)
    return {f'{a}>{b}': f for a, out in flow.items() for b, f in out.items() if f > 0}


def all_pairs(df: pd.DataFrame, pairs: list[tuple[str, str]] | None = None) -> pd.DataFrame:
    """Max-flow for every MTU and every ordered zone pair.

    Returns a DataFrame with the same index as ``df`` and one column per
    pair, named 'FROM>TO'. For neighbours this is at least the border ATC.
    """
    zs = zones(df)
    if pairs is None:
        pairs = [(a, b) for a in zs for b in zs if a != b]
    _check_zones(zs, {z for pair in pairs for z in pair})
    rows = []
    for _, atc in df[borders(df.columns)].iterrows():
        g = build_graph(atc)
        rows.append({f'{a}>{b}': nx.maximum_flow_value(g, a, b) for a, b in pairs})
    return pd.DataFrame(rows, index=df.index)


def hourly(flow: pd.DataFrame) -> pd.DataFrame:
    """Hourly capacity = minimum of the 15-min capacities within each hour."""
    return flow.resample('1h').min()
