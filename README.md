# food-redistribution-mvp
This repository provides a reproducible Python reference implementation of the weighted scoring and Dijkstra routing workflow described in **A Bilateral Mobile Marketplace with Weighted Matching and Dijkstra-Based Routing to Improve Food Distribution in Metropolitan Lima**.

It contains a **Synthetic Demonstration Dataset** and local benchmarking scripts. It is not the mobile application's production source code. No live donation records, real participant identities, real-time traffic feed, or measured mobile-interface latency are included. Implemented details that were unspecified in the manuscript are explicit demonstration assumptions below; confirm them against the actual app before claiming implementation equivalence.

## Quick start

Requires Python 3.10 or later. From this directory:

```bash
python -m pip install -r requirements.txt
python benchmark_demo.py --output-dir results
```

The default execution generates 50 offers and 50 requests, performs correctness checks and 10 warm-up calls per function, then times each function 100 times. It prints median and 95th-percentile execution times in milliseconds. No API keys or external mapping services are required.

### Google Colab

Upload `benchmark_demo.py` in the Files panel, then execute:

```python
!pip -q install networkx==3.4.2
!python benchmark_demo.py --output-dir results
```

Download all generated evidence:

```python
import shutil
from google.colab import files
shutil.make_archive('benchmark_results', 'zip', 'results')
files.download('benchmark_results.zip')
```

Colab measures its remote execution environment, not the user's phone or laptop. Timing values vary between runs and machines; preserve the raw results and environment metadata for the reported run.

## Files

| File | Purpose |
|---|---|
| `benchmark_demo.py` | Dataset generator, scoring, graph construction, Dijkstra, correctness checks, timing and export |
| `requirements.txt` | Pinned NetworkX dependency |
| `example_results/synthetic_demo_data.csv` | Included 100-row synthetic dataset generated with seed 42 |
| `example_results/synthetic_graph.graphml` | Exact synthetic graph used in the included run |
| `example_results/benchmark_raw.csv` | One row per iteration, with both timings and route identifiers |
| `example_results/benchmark_summary.json` | Workload, software versions, platform, file hashes, summary statistics and timing exclusions |
| `example_results/performance_measurements.md` | Results paragraph generated from actual measured values |
| `response_to_reviewers.md` | Qualified response draft; complete repository link after publication |

The `example_results` directory contains an assistant execution-environment run, not measurements from the authors' devices. A normal run writes a separate `results` directory. Do not average or cherry-pick results from different environments.

## Synthetic data and provenance

Every row is labeled `SYNTHETIC_DEMONSTRATION`. Rows are offers or requests, not completed transactions or observed decisions. IDs, coordinates, quantities, urgency, availability, and history counts are generated. A fixed random seed makes the inputs reproducible in the recorded software environment; execution times are not deterministic.

Coordinates are sampled from an approximate eastern Lima/Ate envelope: latitude -12.080 to -12.020 and longitude -76.965 to -76.880. This rectangle is not an official district boundary, a geocoded registry, or a set of verified accessible locations. Some generated points may not be serviceable. Distributions are illustrative and have not been calibrated against real donation operations.

### Data dictionary

| Column | Meaning and generation rule |
|---|---|
| `record_id` | Unique synthetic ID: O for offer; R for request |
| `record_type` | `offer` or `request` |
| `data_origin` | Always `SYNTHETIC_DEMONSTRATION` |
| `seed` | Generator seed; default 42 |
| `area_label` | Approximate demonstration envelope label |
| `latitude`, `longitude` | Decimal-degree simulated coordinates; six decimals |
| `food_type` | Rice, oats, lentils, beans, potatoes, sweet potatoes, apples or bananas |
| `food_family` | Grains, pulses, tubers or fruit |
| `quantity_kg` | Uniformly sampled 5–100 kg, one decimal; available for offers, requested for requests |
| `urgency` | Request only: high, medium or low, sampled uniformly |
| `max_distance_km` | Request only: 3–15 km, one decimal |
| `history_attempts` | Offer only: integer 0–40 |
| `history_completed` | Offer only: integer between ceil(0.6 × attempts) and attempts; zero at cold start |
| `availability_hours` | Offer only: 6, 12, 24 or 48 hours; illustrative |

Blank cells mean not applicable, not an observed missing value. Quantities and availability are exported for transparency and future model extensions but do not constrain the current ranking or route.

## Scoring model

```text
score = 0.35*S_food + 0.25*S_distance + 0.25*S_urgency + 0.15*S_history
```

- `S_food`: 1 for the same food type, 0.5 for the same food family, otherwise 0. These families are illustrative, not a validated nutritional substitution policy.
- `S_distance = max(0, 1 - haversine_distance_km / max_distance_km)`. Straight-line distance is used for scoring; graph distance is used for routing.
- `S_urgency`: high = 1, medium = 0.6, low = 0.3. It is constant across all offers for one request and cannot change their relative order.
- `S_history`: donor completed/attempted transactions, or 0.5 with no history. This cold-start rule and donor-only history are reference-code choices, not verified details of the mobile app.

Each request gets a fully sorted list of offers. Equal scores are resolved by offer ID. There is no global matching, stock depletion or vehicle assignment; one offer can appear first for multiple requests. Incompatible or beyond-distance offers receive lower sub-scores but are not excluded. The score is a preference function, not an eligibility or food-safety validation rule. User confirmation and real feasibility checks would be required before operational use.

## Dijkstra and graph assumptions

The graph is a connected, undirected 21 × 21 grid (441 grid nodes) plus one endpoint node for each offer and request. Each endpoint connects to its nearest grid node. The default graph has 541 nodes and 940 edges. Grid edges and endpoint connectors use rounded positive integer distances in metres, derived from the coordinates.

`networkx.single_source_dijkstra` returns a minimum-weight path and distance for a selected pair. The network is **synthetic**, not OpenStreetMap or verified Lima streets. It contains no turn restrictions, traffic, travel-time observations, vehicle capacities or service windows. Endpoint connections and the grid do not imply physical road accessibility. Routes must not be used for actual navigation.

API reference: https://networkx.org/documentation/stable/reference/algorithms/generated/networkx.algorithms.shortest_paths.weighted.single_source_dijkstra.html

## Benchmark protocol and interpretation

1. Generate inputs and the graph; export data; check arithmetic and paths.
2. Run 10 untimed warm-up calls for each function.
3. Run 100 timed calls for each function using `time.perf_counter_ns()`.
4. Matching: every call recomputes all 2,500 pair scores, including distances, and fully sorts offers for each of the 50 requests.
5. Routing: every call computes one selected pair; cycle through the 50 request-specific top-ranked pairs (two cycles by default).
6. Export individual timings. Report the median and the linearly interpolated 95th percentile at index `(n-1)*0.95` in sorted observations.

Calls are sequential, single-process, and warm. Results are recomputed, not returned from a route-result cache. Graph/data preparation, endpoint snapping, exports, databases, network calls, mobile UI, and rendering are excluded. Matching is a full batch; routing is a single-pair query. Their reported times have different work units and must not be interpreted as an end-to-end user transaction.

These tests provide preliminary evidence about local computational cost only. They are not stress tests, concurrent-load tests, operational validation, or mobile latency tests. Low local execution times do not prove that the integrated application meets a mobile responsiveness target. The 100 repetitions are timing observations, not 100 independent donation operations or user-study participants.

For larger sequential workloads, use separate output directories, for example:

```bash
python benchmark_demo.py --offers 100 --requests 100 --runs 100 --output-dir results_100
python benchmark_demo.py --offers 250 --requests 250 --grid-side 41 --runs 100 --output-dir results_250
```

These commands have not been reported as stress-test results. Document hardware and compare the same work unit across runs. Actual mobile validation requires instrumentation on the integrated app, named devices, network conditions, and submission-to-display timing. Actual stress testing requires a defined load model and concurrency levels.

## Correctness and reproducibility

The script checks corrected Table 5 scores and ranking, normalized score bounds, constant within-request urgency, graph connectivity, a known-answer shortest path, and route-cost reconstruction. These checks do not establish operational effectiveness. The source and dataset SHA-256 hashes, seed, Python/NetworkX versions, execution date, platform, workload and raw timing observations are saved. A CPU description may be unavailable in a virtual environment; record physical hardware separately when known.

The reference scorer costs O(r*m) for fixed four-criterion scoring plus O(r*m*log(m)) for sorting. Dijkstra cost depends on the implementation and graph structure; NetworkX uses heap-based shortest-path routines. Do not assume this reference code's data structures or timings are those of the deployed application.

## Research reporting

Use the generated `performance_measurements.md` as a paragraph describing this **reference-code synthetic microbenchmark**. Do not substitute its values into a claim about the actual mobile application. No empirical weight sensitivity, donation success rate, allocation-quality benefit, delivery-time improvement or real-time dataset is provided here. Synthetic evidence improves repeatability but does not satisfy a request for observed donation data by itself.

The revised article was reconstructed from the supplied PDF because the short-paper DOCX was not available among the attachments. The bibliography and source figures were retained; journal-template compliance must be checked against the venue's template. The article does not silently incorporate the example benchmark as if it measured the original app.
