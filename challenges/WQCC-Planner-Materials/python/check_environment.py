"""Bounded local import/transpilation/Aer check; no credentials or network calls."""
from pathlib import Path
import argparse
import json
import subprocess
import sys
import time


CHECK = r'''
import json, sys, time
from importlib.metadata import version
t = time.perf_counter()
print("phase: scientific imports", flush=True)
from qiskit import QuantumCircuit, transpile
from qiskit_aer import AerSimulator
import qiskit_addon_cutting
print("phase: level-3 transpilation (includes installed plugin discovery)", flush=True)
qc = QuantumCircuit(2)
qc.h(0)
qc.cx(0, 1)
qc.measure_all()
backend = AerSimulator(max_parallel_threads=1)
compiled = transpile(qc, backend, optimization_level=3, seed_transpiler=20261001)
print("phase: 64-shot local Aer check", flush=True)
counts = backend.run(compiled, shots=64, seed_simulator=20261001).result().get_counts()
assert sum(counts.values()) == 64 and set(counts).issubset({"00", "11"})
print(json.dumps({"status": "pass", "python": sys.executable,
    "versions": {name: version(name) for name in
        ["qiskit", "qiskit-aer", "qiskit-addon-cutting", "qiskit-ibm-runtime", "numpy", "scipy"]},
    "physical_shots": 64, "counts": counts, "seconds": time.perf_counter()-t}), flush=True)
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=120,
                        help="Total child-process timeout in seconds, default 120")
    parser.add_argument("--json", type=Path, help="Optional local JSON diagnostic report")
    args = parser.parse_args()
    if not 0 < args.timeout < float("inf"):
        parser.error("--timeout must be finite and positive")
    began = time.perf_counter()
    try:
        result = subprocess.run([sys.executable, "-u", "-c", CHECK],
            text=True, capture_output=True, timeout=args.timeout, check=False)
        print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, file=sys.stderr, end="")
        last = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""
        record = json.loads(last) if result.returncode == 0 else {
            "status": "failed", "returncode": result.returncode,
            "stdout": result.stdout, "stderr": result.stderr}
    except subprocess.TimeoutExpired as exc:
        def decode(value):
            return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value or ""
        record = {"status": "timeout", "seconds": args.timeout,
                  "stdout": decode(exc.stdout), "stderr": decode(exc.stderr)}
        print(record["stdout"], end="")
        print("Environment check timed out. Inspect the last printed phase; this is not a planner accuracy failure.", file=sys.stderr)
    record["total_seconds"] = time.perf_counter() - began
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return 0 if record["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
