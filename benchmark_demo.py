#!/usr/bin/env python3
"""Synthetic reference implementation; NOT the instrumented mobile application.

Python >=3.10; pip install networkx==3.4.2
Run: python benchmark_demo.py --output-dir results
All geographic points, inventory, histories, and graph edges are simulated.
"""
import argparse
import csv
import hashlib
import json
import math
import os
import platform
import random
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter_ns

try:
    import networkx as nx
except ImportError:
    raise SystemExit("Install the dependency first: python -m pip install networkx==3.4.2")

VERSION = "1.0.0"
WEIGHTS = (0.35, 0.25, 0.25, 0.15)
# Approximate eastern Lima/Ate demonstration envelope, NOT an official boundary.
LAT_RANGE = (-12.080, -12.020)
LON_RANGE = (-76.965, -76.880)
FOODS = {"rice": "grains", "oats": "grains", "lentils": "pulses",
         "beans": "pulses", "potatoes": "tubers", "sweet_potatoes": "tubers",
         "apples": "fruit", "bananas": "fruit"}
URGENCY = {"high": 1.0, "medium": 0.6, "low": 0.3}


def haversine_km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl / 2)**2
    return 6371.0088 * 2 * math.asin(math.sqrt(min(1.0, max(0.0, a))))


def generate_data(n_offers, n_requests, seed):
    rng = random.Random(seed)
    records = []
    for kind, count, prefix in (("offer", n_offers, "O"), ("request", n_requests, "R")):
        for i in range(count):
            food = rng.choice(list(FOODS))
            attempts = rng.randint(0, 40) if kind == "offer" else None
            completed = rng.randint(math.ceil(attempts * 0.6), attempts) if attempts else 0
            records.append({
                "record_id": f"{prefix}{i+1:04d}", "record_type": kind,
                "data_origin": "SYNTHETIC_DEMONSTRATION", "seed": seed,
                "area_label": "Approximate Lima/Ate demonstration envelope",
                "latitude": round(rng.uniform(*LAT_RANGE), 6),
                "longitude": round(rng.uniform(*LON_RANGE), 6),
                "food_type": food, "food_family": FOODS[food],
                "quantity_kg": round(rng.uniform(5, 100), 1),
                "urgency": rng.choice(list(URGENCY)) if kind == "request" else "",
                "max_distance_km": round(rng.uniform(3, 15), 1) if kind == "request" else "",
                "history_attempts": attempts if kind == "offer" else "",
                "history_completed": completed if kind == "offer" else "",
                "availability_hours": rng.choice([6, 12, 24, 48]) if kind == "offer" else "",
            })
    return records


def pair_score(offer, request):
    """Explicit DEMONSTRATION choices where the manuscript was underspecified.

    S_distance = max(0, 1 - straight_line_distance / max_distance).
    History is donor completion ratio; 0.5 is the cold-start default.
    Soft ranking only: no stock depletion, eligibility filters or joint assignment.
    """
    food = (1.0 if offer["food_type"] == request["food_type"] else
            0.5 if offer["food_family"] == request["food_family"] else 0.0)
    distance = haversine_km(offer["latitude"], offer["longitude"],
                            request["latitude"], request["longitude"])
    proximity = max(0.0, 1.0 - distance / request["max_distance_km"])
    urgency = URGENCY[request["urgency"]]
    attempts = offer["history_attempts"]
    history = offer["history_completed"] / attempts if attempts else 0.5
    subscores = (food, proximity, urgency, history)
    return sum(w*s for w, s in zip(WEIGHTS, subscores)), subscores, distance


def rank_all(offers, requests):
    """Score and fully sort every offer for EVERY request (2500 pairs by default)."""
    result = {}
    for request in requests:
        candidates = []
        for offer in offers:
            score, subscores, distance = pair_score(offer, request)
            candidates.append({"offer_id": offer["record_id"], "score": score,
                               "subscores": subscores, "straight_line_km": distance})
        result[request["record_id"]] = sorted(candidates, key=lambda x: (-x["score"], x["offer_id"]))
    return result


def build_synthetic_graph(records, side):
    """Connected undirected grid plus one leaf per actor; not Lima's road graph.

    Integer metre edge costs avoid floating-point accumulation in Dijkstra.
    Endpoint snapping and graph construction are outside the timed routine.
    """
    graph = nx.Graph(data_origin="SYNTHETIC_DEMONSTRATION", edge_unit="metres")
    grid_nodes = []
    for i in range(side):
        for j in range(side):
            node = f"G{i:04d}_{j:04d}"
            lat = LAT_RANGE[0] + i * (LAT_RANGE[1]-LAT_RANGE[0])/(side-1)
            lon = LON_RANGE[0] + j * (LON_RANGE[1]-LON_RANGE[0])/(side-1)
            graph.add_node(node, latitude=lat, longitude=lon)
            grid_nodes.append(node)
            for other in ([f"G{i-1:04d}_{j:04d}"] if i else []) + ([f"G{i:04d}_{j-1:04d}"] if j else []):
                d = haversine_km(lat, lon, graph.nodes[other]["latitude"], graph.nodes[other]["longitude"])
                graph.add_edge(node, other, distance_m=max(1, round(d*1000)))
    for record in records:
        node = record["record_id"]
        graph.add_node(node, latitude=record["latitude"], longitude=record["longitude"])
        def distance_to(other):
            return haversine_km(record["latitude"], record["longitude"],
                                graph.nodes[other]["latitude"], graph.nodes[other]["longitude"])
        nearest = min(grid_nodes, key=distance_to)
        graph.add_edge(node, nearest, distance_m=max(1, round(distance_to(nearest)*1000)))
    return graph


def route(graph, source, target):
    return nx.single_source_dijkstra(graph, source, target, weight="distance_m")


def percentile(values, p):
    """Linear interpolation: index=(n-1)*p; same convention as NumPy linear."""
    ordered = sorted(values)
    index = (len(ordered)-1)*p
    lo, hi = math.floor(index), math.ceil(index)
    return ordered[lo] + (ordered[hi]-ordered[lo])*(index-lo)


def write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def check_correctness(offers, requests, rankings, graph, pairs):
    # Published illustrative Table 5 regression check, including the revised ranking.
    rows = [(1, .85, 1, .9), (.5, .7, 1, .8), (1, .4, 1, .7), (.5, .3, 1, .6)]
    expected = [.9475, .7200, .8050, .5900]
    for row, exp in zip(rows, expected):
        assert math.isclose(sum(w*s for w, s in zip(WEIGHTS, row)), exp, abs_tol=1e-12)
    assert sorted(range(4), key=lambda i: -expected[i]) == [0, 2, 1, 3]
    assert len(rankings) == len(requests)
    for request in requests:
        ranked = rankings[request["record_id"]]
        assert len(ranked) == len(offers)
        assert all(0 <= x["score"] <= 1 for x in ranked)
        assert all(x["subscores"][2] == URGENCY[request["urgency"]] for x in ranked)
    assert nx.is_connected(graph)
    # Independent known-answer path test; not a timing measurement.
    small = nx.Graph()
    small.add_weighted_edges_from([("a", "b", 2), ("b", "c", 3), ("a", "c", 9)], weight="distance_m")
    assert route(small, "a", "c") == (5, ["a", "b", "c"])
    for source, target in pairs:
        distance, path = route(graph, source, target)
        assert path[0] == source and path[-1] == target
        assert distance == sum(graph[u][v]["distance_m"] for u, v in zip(path, path[1:]))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offers", type=int, default=50)
    parser.add_argument("--requests", type=int, default=50)
    parser.add_argument("--runs", type=int, default=100)
    parser.add_argument("--warmups", type=int, default=10)
    parser.add_argument("--grid-side", type=int, default=21)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output-dir", type=Path, default=Path("results"))
    args = parser.parse_args(argv)
    if min(args.offers, args.requests, args.runs) < 1 or args.grid_side < 2 or args.warmups < 0:
        parser.error("Counts/runs must be positive, grid-side >=2 and warmups >=0.")
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    records = generate_data(args.offers, args.requests, args.seed)
    offers = [x for x in records if x["record_type"] == "offer"]
    requests = [x for x in records if x["record_type"] == "request"]
    write_csv(out/"synthetic_demo_data.csv", records)
    graph = build_synthetic_graph(records, args.grid_side)
    nx.write_graphml(graph, out/"synthetic_graph.graphml")
    rankings = rank_all(offers, requests)
    pairs = [(rankings[r["record_id"]][0]["offer_id"], r["record_id"]) for r in requests]
    check_correctness(offers, requests, rankings, graph, pairs)
    for i in range(args.warmups):
        rank_all(offers, requests)
        route(graph, *pairs[i % len(pairs)])
    times = []
    for i in range(args.runs):
        start = perf_counter_ns()
        current = rank_all(offers, requests)
        matching_ms = (perf_counter_ns()-start)/1_000_000
        # Select one prioritized pair outside the routing timing interval.
        target = requests[i % len(requests)]["record_id"]
        source = current[target][0]["offer_id"]
        start = perf_counter_ns()
        distance, path = route(graph, source, target)
        routing_ms = (perf_counter_ns()-start)/1_000_000
        times.append({"iteration": i+1, "matching_batch_ms": matching_ms,
                      "routing_single_pair_ms": routing_ms, "source": source,
                      "target": target, "route_distance_m": distance, "path_nodes": len(path)})
    write_csv(out/"benchmark_raw.csv", times)
    summaries = {}
    for key in ("matching_batch_ms", "routing_single_pair_ms"):
        values = [x[key] for x in times]
        summaries[key] = {"median_ms": statistics.median(values), "p95_ms": percentile(values, .95)}
        print(f"{key}: median={summaries[key]['median_ms']:.6f} ms; p95={summaries[key]['p95_ms']:.6f} ms")
    source_path = Path(__file__)
    metadata = {"scope": "Local sequential reference-code microbenchmark, NOT mobile latency or stress testing",
        "data_origin": "SYNTHETIC_DEMONSTRATION", "version": VERSION,
        "utc_executed_at": datetime.now(timezone.utc).isoformat(),
        "python": sys.version, "networkx": nx.__version__, "platform": platform.platform(),
        "machine": platform.machine(), "processor": platform.processor(), "cpu_count": os.cpu_count(),
        "script_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
        "dataset_sha256": hashlib.sha256((out/"synthetic_demo_data.csv").read_bytes()).hexdigest(),
        "seed": args.seed, "offers": args.offers, "requests": args.requests,
        "pairs_scored_per_matching_run": args.offers*args.requests,
        "runs_per_function": args.runs, "warmups_per_function": args.warmups,
        "graph_nodes": graph.number_of_nodes(), "graph_edges": graph.number_of_edges(),
        "grid_side": args.grid_side, "distinct_route_pairs": len(set(pairs)),
        "matching_scope": "All pair scores, haversine distances and per-request full sorting",
        "routing_scope": "One selected pair, Dijkstra path and distance; pairs cycled in request order",
        "excluded": ["data generation", "graph construction", "snapping", "file I/O", "UI", "network", "database"],
        "percentile_method": "Linear interpolation at (n-1)*0.95",
        "results": summaries}
    (out/"benchmark_summary.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    m, r = summaries["matching_batch_ms"], summaries["routing_single_pair_ms"]
    report = (f"# Local synthetic microbenchmark report\n\n"
        f"The Python reference implementation (version {VERSION}, SHA-256 `{metadata['script_sha256']}`) "
        f"was evaluated in a {platform.machine()} execution environment using Python {platform.python_version()} "
        f"and NetworkX {nx.__version__}. The synthetic workload contained {args.offers} offers and "
        f"{args.requests} requests, with a graph of {graph.number_of_nodes()} vertices and "
        f"{graph.number_of_edges()} undirected edges. After {args.warmups} warm-up calls per function, "
        f"{args.runs} timed calls per function were executed sequentially. Each matching call scored "
        f"{args.offers*args.requests} pairs and sorted the offers for every request; median and "
        f"95th-percentile times were {m['median_ms']:.6f} ms and {m['p95_ms']:.6f} ms. "
        f"Each routing call computed one selected pair, cycling through {len(pairs)} pairs; median and "
        f"95th-percentile times were {r['median_ms']:.6f} ms and {r['p95_ms']:.6f} ms. "
        "These measurements describe warm local computation on this synthetic workload. They exclude "
        "data and graph preparation, file I/O, database and network access, and mobile rendering. "
        "They neither establish end-to-end mobile responsiveness nor constitute concurrency or stress testing. "
        "Synthetic graph distances are not verified street routes.\n")
    (out/"performance_measurements.md").write_text(report, encoding="utf-8")
    print(f"Saved data, graph, raw times, metadata and report to {out.resolve()}")
    print("Synthetic reference benchmark only; no live donations, real road map or mobile UI measured.")


if __name__ == "__main__":
    main()
