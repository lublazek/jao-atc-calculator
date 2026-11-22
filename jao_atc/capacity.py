"""Cross-zonal capacity between any two bidding zones, as max-flow over border ATCs."""
from __future__ import annotations

import networkx as nx
import pandas as pd


def zones(df: pd.DataFrame) -> list[str]:
    """Bidding zones appearing in the border columns ('CZ>SK', ...)."""
    return sorted({z for col in df.columns for z in col.split('>')})


def build_graph(atc: pd.Series) -> nx.DiGraph:
    """One MTU of border ATCs -> directed graph. Negative or missing ATC counts as 0."""
    g = nx.DiGraph()
    for border, value in atc.items():
        src, dst = border.split('>')
        g.add_edge(src, dst, capacity=max(float(value), 0.0) if pd.notna(value) else 0.0)
    return g


def max_flow(atc: pd.Series, src: str, dst: str) -> float:
    """Maximum MW that can flow from src to dst in one MTU, using all paths at once."""
    return nx.maximum_flow_value(build_graph(atc), src, dst)


def max_flow_paths(atc: pd.Series, src: str, dst: str) -> dict[str, float]:
    """How the max-flow from src to dst is split over the borders (only borders with flow)."""
    _, flow = nx.maximum_flow(build_graph(atc), src, dst)
    return {f'{a}>{b}': f for a, out in flow.items() for b, f in out.items() if f > 0}


def all_pairs(df: pd.DataFrame, pairs: list[tuple[str, str]] | None = None) -> pd.DataFrame:
    """Max-flow for every MTU and every ordered zone pair.

    Returns a DataFrame with the same index as ``df`` and one column per
    pair, named 'FROM>TO'. For neighbours this is at least the border ATC.
    """
    if pairs is None:
        zs = zones(df)
        pairs = [(a, b) for a in zs for b in zs if a != b]
    rows = []
    for _, atc in df.iterrows():
        g = build_graph(atc)
        rows.append({f'{a}>{b}': nx.maximum_flow_value(g, a, b) for a, b in pairs})
    return pd.DataFrame(rows, index=df.index)
