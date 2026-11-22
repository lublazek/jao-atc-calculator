# jao-atc-calculator

Cross-zonal intraday capacity between any two Core bidding zones, calculated from
the ATCs that JAO publishes for each intraday capacity calculation run (IDCC a–e).

JAO publishes ATCs per **border** (e.g. CZ→SK). This project turns them into the
capacity between any **pair of zones** (e.g. CZ→HU), using every possible route
at once (max-flow).

Data source: [JAO Publication Tool – Core ID](https://publicationtool.jao.eu/coreID/),
dataset *Final ATC for SIDC* (`IDCC{A..E}_intradayAtc`).

## IDCC runs

For delivery day **D**, local time (CET/CEST):

| Run     | Calculated | Covers           |
|---------|------------|------------------|
| IDCC(a) | D-1 15:00  | whole day D      |
| IDCC(b) | D-1 22:00  | whole day D      |
| IDCC(c) | D 04:00    | D 06:00 onwards  |
| IDCC(d) | D 10:00    | D 12:00 onwards  |
| IDCC(e) | D 16:00    | D 18:00 onwards  |

Each downloaded run is trimmed to the MTUs it covers. `latest` combines the runs:
for every 15-min MTU it takes the newest run covering it.

## Setup

```bash
pip install -r requirements.txt          # pandas, requests, networkx
pip install -r requirements-dev.txt      # + pytest, for running the tests
```

In Google Colab:

```python
!git clone https://github.com/lublazek/jao-atc-calculator.git
%cd jao-atc-calculator
!pip install -q -r requirements.txt
```

## Usage

### Notebook

Open `IDCC_capacities.ipynb`, set the first cell and run all cells:

```python
RUN = 'latest'   # 'A'..'E', or 'latest' = newest run for every MTU
DAY = 'today'    # 'today', 'tomorrow' or '2026-11-21'
```

and in the second cell which zones to print:

```python
COUNTRIES = ['CZ', 'SK', 'HU']
```

It prints import/export capacity to every other zone, per 15 minutes and per hour.

### Command line

Download runs and save them as CSV in `data/`:

```bash
python -m jao_atc.download --day 2026-11-21 --runs ABCDE
python -m jao_atc.download --day tomorrow --runs AB
```

### Python

```python
from jao_atc.download import fetch_all, select
from jao_atc.capacity import all_pairs, hourly, max_flow_paths

dfs  = fetch_all('today')            # {'A': df, 'B': df, ...}; unpublished runs skipped
df   = select(dfs, 'latest')         # border ATCs per MTU, columns like 'CZ>SK'
flow = all_pairs(df)                 # capacity for every zone pair, columns like 'CZ>HU'
flow_h = hourly(flow)                # min of the four quarter-hours

max_flow_paths(df.iloc[0], 'CZ', 'HU')   # which borders carry the CZ→HU flow
```

## How the capacity is calculated

Every zone is a node and every border ATC is a one-way pipe with that capacity
(negative ATC counts as 0). The capacity from zone X to zone Y is the **maximum
flow** through this network: all routes may be used at the same time, but each
border's ATC is used only once across them.

Example, CZ→HU:

```
CZ → SK → HU    CZ>SK = 300, SK>HU = 500    → 300
CZ → AT → HU    CZ>AT = 400, AT>HU = 200    → 200
                                    max-flow = 500
```

The result always equals the weakest set of borders separating X from Y
(here CZ>SK + AT>HU = 500), which is a handy way to check a number.

**Hourly** capacity is the minimum of the four 15-min capacities in that hour.

### Limitations

- Each pair's capacity is **standalone**: pairs share borders, so values for
  different pairs cannot be added up.
- Only the ATCs published by JAO are used; no flow-based or loop-flow effects
  beyond what is already in the ATCs.

## Data checks

The downloader warns when a run has missing MTUs (a full day has 92/96/100 MTUs
on DST days), drops rows outside the delivery day and duplicate MTUs, and skips
a run whose download fails without losing the others. `latest` warns when an
older run had to fill a gap in a newer one.

## Tests

```bash
python -m pytest -q tests
```

## Project structure

```
IDCC_capacities.ipynb     notebook: settings, calculation, printed tables
jao_atc/download.py       JAO download, run timing, latest-run view, CSV save/load
jao_atc/capacity.py       max-flow capacity between zones, hourly aggregation
tests/                    unit tests (mocked HTTP, no network needed)
```

## License

MIT – see [LICENSE](LICENSE).
