"""Plan, execute, and reconstruct a bounded circuit-cutting experiment.

Qiskit add-on APIs generate the actual QPD experiments and independently check
our reconstruction. No full-circuit simulation is used by the planner/executor.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
import math
import multiprocessing as mp
import time
import numpy as np
from qiskit import QuantumCircuit, transpile
from qiskit.primitives import SamplerResult
from qiskit.quantum_info import PauliList
from qiskit.result import QuasiDistribution
from qiskit.transpiler import CouplingMap
from qiskit_aer import AerSimulator
from qiskit_aer.noise import NoiseModel, depolarizing_error, ReadoutError
from qiskit_addon_cutting import (partition_problem, generate_cutting_experiments,
                                  reconstruct_expectation_values)
from qiskit_addon_cutting.automated_cut_finding import (
    find_cuts, OptimizationParameters, DeviceConstraints)
from qiskit_addon_cutting.utils.observable_grouping import ObservableCollection
from qiskit_addon_cutting.qpd import TwoQubitQPDGate
from .instances import Instance, HardwareProfile
from .statistics import allocate_shots, product_variance, sampling_interval


class InfeasiblePlan(ValueError):
    """A strategy cannot produce a plan within the stated teaching constraints."""


@dataclass(frozen=True)
class Limits:
    max_qpd_terms: int = 256
    max_experiments: int = 2048
    max_overhead: float = 10000.0
    max_backjumps: int = 1000
    cut_search_seconds: float = 20.0
    min_shots_per_experiment: int = 2


@dataclass
class Experiment:
    circuit: QuantumCircuit
    term: int
    qpd_term: int
    partition: Any
    weight: float
    parity_mask: int
    shots: int = 0
    logical_qubits: list[int] = field(default_factory=list)
    initial_physical_layout: list[int] = field(default_factory=list)
    final_physical_layout: list[int] = field(default_factory=list)


@dataclass
class TermPlan:
    pauli: str
    observable_coefficient: float
    qpd_coefficients: list
    subobservables: dict
    experiment_indices: dict[Any, list[int]]


@dataclass
class ExecutionPlan:
    instance_id: str
    strategy: str
    decision: str
    allocation: str
    experiments: list[Experiment]
    terms: list[TermPlan]
    products: list[tuple[float, list[int]]]
    constant: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> dict[str, Any]:
        return dict(instance_id=self.instance_id, strategy=self.strategy,
                    decision=self.decision, allocation=self.allocation,
                    experiments=len(self.experiments),
                    physical_shots=sum(e.shots for e in self.experiments),
                    maximum_experiment_width=max((e.circuit.num_qubits for e in self.experiments), default=0),
                    maximum_two_qubit_depth=max((e.circuit.depth(lambda i: len(i.qubits) == 2)
                                                 for e in self.experiments), default=0),
                    shot_weighted_two_qubit_gates=sum(
                        e.shots * sum(len(i.qubits) == 2 for i in e.circuit.data)
                        for e in self.experiments),
                    **self.metadata)


def _finder_worker(connection, circuit, width, seed, limits):
    """Top-level spawn target gives search a real wall-clock stop on Windows."""
    try:
        output = find_cuts(circuit,
            OptimizationParameters(seed=seed, max_gamma=math.sqrt(limits.max_overhead),
                                   max_backjumps=limits.max_backjumps,
                                   gate_lo=True, wire_lo=False),
            DeviceConstraints(qubits_per_subcircuit=width))
        connection.send((True, output))
    except Exception as exc:
        connection.send((False, f"{type(exc).__name__}: {exc}"))
    finally:
        connection.close()


def _bounded_find(circuit, width, seed, limits):
    ctx = mp.get_context("spawn")
    receive, send = ctx.Pipe(duplex=False)
    process = ctx.Process(target=_finder_worker, args=(send, circuit, width, seed, limits))
    process.start()
    send.close()
    try:
        if not receive.poll(limits.cut_search_seconds):
            process.terminate()
            raise InfeasiblePlan(f"automatic cut search exceeded {limits.cut_search_seconds:g}s (includes worker startup)")
        try:
            success, output = receive.recv()
        except EOFError as exc:
            raise InfeasiblePlan("cut finder worker exited without a result") from exc
        if not success:
            raise InfeasiblePlan(f"automatic cut search failed: {output}")
        return output
    finally:
        receive.close()
        process.join(timeout=2)
        if process.is_alive():
            process.terminate()
            process.join()


def _compile(circuits: list[QuantumCircuit], instance: Instance) -> list[QuantumCircuit]:
    if not circuits:
        return []
    edges = instance.hardware.edges(instance.max_width)
    coupling = CouplingMap(edges)
    if instance.max_width == 1:
        coupling.add_physical_qubit(0)
    return transpile(circuits, basis_gates=["rz", "sx", "x", "cx", "reset"],
                     coupling_map=coupling, optimization_level=3,
                     seed_transpiler=instance.seed, num_processes=1)


def _connected_partition_labels(circuit: QuantumCircuit) -> list[int | None]:
    """Connectivity excluding marked cuts, with Qiskit's documented ordering.

    Connected components are ordered by lowest input-qubit index. Idle wires
    have label None; QPD instructions still count as using their qubit wires.
    No private add-on helper is called.
    """
    parent = list(range(circuit.num_qubits))
    used = set()
    def find(q):
        while parent[q] != q:
            parent[q] = parent[parent[q]]
            q = parent[q]
        return q
    for instruction in circuit.data:
        indices = [circuit.find_bit(q).index for q in instruction.qubits]
        used.update(indices)
        if not isinstance(instruction.operation, TwoQubitQPDGate) and indices:
            for q in indices[1:]:
                parent[find(q)] = find(indices[0])
    groups = {}
    for q in sorted(used):
        groups.setdefault(find(q), []).append(q)
    labels = [None] * circuit.num_qubits
    for label, group in enumerate(sorted(groups.values(), key=min)):
        for q in group:
            labels[q] = label
    return labels


def plan(instance: Instance, strategy: str = "policy", allocation: str = "coefficient",
         *, limits: Limits | None = None) -> ExecutionPlan:
    """Produce a fixed allocation with no reference-oracle access.

    direct: hardware-aware transpilation, rejects width-infeasible input.
    auto_cut: Qiskit automatic gate-cut finder at max_width (may select no cuts).
    structured_cut: fixed contiguous blocks of at most 2 qubits, teaching baseline.
    policy: simple honest baseline: direct if width fits; otherwise auto_cut.

    Coefficient allocation uses |observable coefficient * QPD coefficient| per
    experiment. This is a fixed heuristic, not an optimal product-estimator rule.
    """
    began = time.perf_counter()
    instance.__post_init__()
    limits = limits or Limits()
    if strategy not in {"direct", "auto_cut", "structured_cut", "policy"}:
        raise ValueError("unknown strategy")
    if allocation not in {"equal", "coefficient"}:
        raise ValueError("allocation must be equal or coefficient")
    if instance.circuit.num_qubits > 10 or instance.max_width > 10:
        raise InfeasiblePlan("starter caps circuits and physical width at 10 qubits")
    selected = ("direct" if instance.circuit.num_qubits <= instance.max_width else "auto_cut") if strategy == "policy" else strategy
    if selected == "direct" and instance.circuit.num_qubits > instance.max_width:
        raise InfeasiblePlan("direct circuit exceeds maximum experiment width")
    circuit = instance.circuit
    metadata: dict[str, Any] = {"selected_strategy": selected}
    if selected == "auto_cut":
        circuit, finder = _bounded_find(circuit, instance.max_width, instance.seed, limits)
        metadata["automatic_finder"] = finder
        partition_labels = _connected_partition_labels(circuit)
    elif selected == "structured_cut":
        block = min(2, instance.max_width)
        partition_labels = [q // block for q in range(circuit.num_qubits)]
    else:
        partition_labels = [0] * circuit.num_qubits
    partition_map = {str(label): [q for q, group in enumerate(partition_labels) if group == label]
                     for label in sorted(set(partition_labels) - {None})}
    cut_locations = []
    for index, instruction in enumerate(circuit.data):
        qubits = [circuit.find_bit(q).index for q in instruction.qubits]
        if isinstance(instruction.operation, TwoQubitQPDGate) or (
                len(qubits) == 2 and len({partition_labels[q] for q in qubits}) > 1):
            original = instance.circuit.data[index].operation
            cut_locations.append(dict(instruction_index=index, gate=original.name,
                                      qubits=qubits, parameters=[float(p) for p in original.params]))
    metadata.update(partition_map=partition_map, cut_locations=cut_locations,
                    mapping_policy="Qiskit optimization_level=3, seeded connectivity-aware layout",
                    topology=instance.hardware.topology,
                    physical_edges=instance.hardware.edges(instance.max_width))
    expts: list[Experiment] = []
    terms: list[TermPlan] = []
    products: list[tuple[float, list[int]]] = []
    constant = 0.0
    overheads: list[float] = []
    cut_counts: list[int] = []
    fragment_widths: list[int] = []
    for term_index, (label, raw_weight) in enumerate(instance.observable.simplify().to_list()):
        weight = float(raw_weight.real)
        if abs(weight) < 1e-14:
            continue
        if set(label) == {"I"}:
            constant += weight
            continue
        problem = partition_problem(circuit, partition_labels=partition_labels,
                                    observables=PauliList([label]))
        widths = [sub.num_qubits for sub in problem.subcircuits.values()]
        if max(widths, default=0) > instance.max_width:
            raise InfeasiblePlan("returned partition exceeds maximum width")
        qpd_terms_bound = math.prod(sum(abs(c) > 0 for c in basis.coeffs) for basis in problem.bases)
        overhead = float(math.prod(b.overhead for b in problem.bases))
        if overhead > limits.max_overhead or qpd_terms_bound > limits.max_qpd_terms:
            raise InfeasiblePlan(f"cut expansion too large: {qpd_terms_bound} QPD terms, overhead {overhead:.3g}")
        if len(expts) + qpd_terms_bound * len(widths) > limits.max_experiments:
            raise InfeasiblePlan("pre-generation experiment-count cap exceeded")
        circuits, coefficients = generate_cutting_experiments(
            problem.subcircuits, problem.subobservables, num_samples=np.inf)
        indices = {}
        for partition, fragment_experiments in circuits.items():
            if len(fragment_experiments) != len(coefficients):
                raise RuntimeError("single-Pauli path expected one experiment per QPD term and partition")
            indices[partition] = []
            collection = ObservableCollection(problem.subobservables[partition])
            observable_mask = collection.groups[0].pauli_bitmasks[0]
            for qpd_index, subexperiment in enumerate(fragment_experiments):
                indices[partition].append(len(expts))
                parity_mask = 0
                for register in subexperiment.cregs:
                    for bit_index, bit in enumerate(register):
                        if register.name == "qpd_measurements" or (
                            register.name == "observable_measurements" and observable_mask & (1 << bit_index)):
                            parity_mask |= 1 << subexperiment.find_bit(bit).index
                expts.append(Experiment(subexperiment, term_index, qpd_index,
                                        partition, abs(weight * coefficients[qpd_index][0]), parity_mask))
                expts[-1].logical_qubits = list(partition_map[str(partition)])
        terms.append(TermPlan(label, weight, coefficients, problem.subobservables, indices))
        for qpd_index, (coefficient, _) in enumerate(coefficients):
            products.append((weight * coefficient, [values[qpd_index] for values in indices.values()]))
        overheads.append(overhead)
        cut_counts.append(len(problem.bases))
        fragment_widths.extend(widths)
    if len(expts) > limits.max_experiments:
        raise InfeasiblePlan("post-generation experiment-count cap exceeded")
    try:
        shots = allocate_shots([1.0 if allocation == "equal" else e.weight for e in expts],
                               instance.shots, limits.min_shots_per_experiment)
    except ValueError as exc:
        raise InfeasiblePlan(str(exc)) from exc
    compiled = _compile([e.circuit for e in expts], instance)
    for experiment, compiled_circuit, count in zip(expts, compiled, shots):
        experiment.circuit, experiment.shots = compiled_circuit, count
        layout = compiled_circuit.layout
        experiment.initial_physical_layout = (layout.initial_index_layout(filter_ancillas=True)
            if layout else list(range(len(experiment.logical_qubits))))
        experiment.final_physical_layout = (layout.final_index_layout(filter_ancillas=True)
            if layout else list(range(len(experiment.logical_qubits))))
    metadata.update(maximum_qpd_overhead=max(overheads, default=1),
                    gate_cuts=max(cut_counts, default=0),
                    logical_fragment_widths=sorted(set(fragment_widths)),
                    planning_seconds=time.perf_counter() - began,
                    shot_allocation_min=min(shots, default=0), shot_allocation_max=max(shots, default=0))
    decision = "cut" if max(cut_counts, default=0) else "direct_or_factorized"
    output = ExecutionPlan(instance.instance_id, strategy, decision, allocation,
                           expts, terms, products, constant, metadata)
    validate_plan(instance, output)
    return output


def validate_plan(instance: Instance, execution_plan: ExecutionPlan) -> None:
    instance.__post_init__()
    if execution_plan.instance_id != instance.instance_id:
        raise ValueError("plan belongs to a different instance")
    if sum(e.shots for e in execution_plan.experiments) > instance.shots:
        raise InfeasiblePlan("plan exceeds the shared physical-shot budget")
    for experiment in execution_plan.experiments:
        if not isinstance(experiment.shots, int) or experiment.shots < 2:
            raise InfeasiblePlan("every measured experiment needs at least 2 integer shots")
        if experiment.circuit.num_qubits > instance.max_width:
            raise InfeasiblePlan("compiled circuit exceeds width")
        if {register.name for register in experiment.circuit.cregs} - {"observable_measurements", "qpd_measurements"}:
            raise ValueError("unexpected measurement registers")
        allowed_edges = {tuple(edge) for edge in instance.hardware.edges(instance.max_width)}
        for instruction in experiment.circuit.data:
            if instruction.operation.name not in {"rz", "sx", "x", "cx", "reset", "measure", "barrier"}:
                raise InfeasiblePlan("experiment contains an operation outside the backend basis")
            if instruction.operation.name == "cx":
                edge = tuple(experiment.circuit.find_bit(q).index for q in instruction.qubits)
                if edge not in allowed_edges:
                    raise InfeasiblePlan("compiled CX violates backend connectivity")


def _noise_model(profile: HardwareProfile, width: int) -> NoiseModel:
    model = NoiseModel()
    for qubit in range(width):
        scale = 1 + 0.1 * qubit
        if profile.one_qubit_error:
            model.add_quantum_error(depolarizing_error(profile.one_qubit_error * scale, 1),
                                    ["sx", "x"], [qubit])
        if profile.readout_error:
            error = profile.readout_error * scale
            model.add_readout_error(ReadoutError([[1-error, error], [error, 1-error]]), [qubit])
    for a, b in profile.edges(width):
        if profile.two_qubit_error:
            scale = 1 + 0.1 * (a + b)
            model.add_quantum_error(depolarizing_error(profile.two_qubit_error * scale, 2), "cx", [a, b])
    return model


class ShotLedger:
    """Small local execution guard, not a security boundary for untrusted code."""
    def __init__(self, budget: int):
        self.budget, self.used = budget, 0
        self.entries: list[dict] = []

    def reserve(self, index: int, shots: int, width: int):
        if shots < 2 or self.used + shots > self.budget:
            raise InfeasiblePlan("execution would exceed shot budget")
        self.used += shots
        self.entries.append(dict(experiment=index, shots=shots, width=width))


def execute(instance: Instance, execution_plan: ExecutionPlan, *, seed: int = 2026,
            confidence: float = 0.95) -> dict[str, Any]:
    """Execute exactly the allocated physical shots; cross-check Qiskit reconstruction."""
    began = time.perf_counter()
    validate_plan(instance, execution_plan)
    simulator = AerSimulator(method="density_matrix", noise_model=_noise_model(instance.hardware, instance.max_width),
                             max_parallel_threads=1, max_parallel_experiments=1)
    ledger = ShotLedger(instance.shots)
    child_seeds = np.random.SeedSequence(seed).spawn(len(execution_plan.experiments))
    means, variances, distributions = [], [], []
    for index, (experiment, seed_sequence) in enumerate(zip(execution_plan.experiments, child_seeds)):
        ledger.reserve(index, experiment.shots, experiment.circuit.num_qubits)
        simulation_seed = int(seed_sequence.generate_state(1, dtype=np.uint32)[0])
        raw = simulator.run(experiment.circuit, shots=experiment.shots,
                            seed_simulator=simulation_seed).result()
        if not raw.success:
            raise RuntimeError(f"simulator experiment failed: {raw.status}")
        counts = raw.get_counts(0)
        observed = sum(counts.values())
        if observed != experiment.shots:
            raise RuntimeError("backend returned a different physical-shot count")
        # Include observable-support bits and all QPD sign bits. Identity
        # fragments can have measured bits that MUST NOT enter the observable.
        integer_counts = {int(bitstring.replace(" ", ""), 2): count for bitstring, count in counts.items()}
        mean = sum((1 if (key & experiment.parity_mask).bit_count() % 2 == 0 else -1) * count
                   for key, count in integer_counts.items()) / observed
        means.append(float(mean))
        variances.append(max(0.0, (1 - mean * mean) / (observed - 1)))
        distributions.append(QuasiDistribution({key: count / observed for key, count in integer_counts.items()}))
    estimate = execution_plan.constant
    variance = 0.0
    for coefficient, indices in execution_plan.products:
        estimate += coefficient * float(np.prod([means[i] for i in indices]))
        variance += coefficient ** 2 * product_variance([means[i] for i in indices],
                                                        [variances[i] for i in indices])
    official = execution_plan.constant
    for term in execution_plan.terms:
        results = {label: SamplerResult([distributions[i] for i in indices], [{} for _ in indices])
                   for label, indices in term.experiment_indices.items()}
        official += term.observable_coefficient * reconstruct_expectation_values(
            results, term.qpd_coefficients, term.subobservables)[0]
    if not np.isclose(estimate, official, atol=1e-10, rtol=1e-10):
        raise RuntimeError(f"independent reconstruction disagrees with Qiskit: {estimate} vs {official}")
    interval = sampling_interval(means, [e.shots for e in execution_plan.experiments],
                                 execution_plan.products, execution_plan.constant, 1-confidence)
    return dict(instance_id=instance.instance_id, seed=seed, estimate=float(estimate),
                sampling_standard_error_approx=float(math.sqrt(max(0.0, variance))),
                sampling_interval=list(interval), confidence=confidence,
                interval_method="union-Hoeffding with interval products; fixed allocation; noisy estimand",
                uncertainty_warning="Sampling uncertainty excludes hardware bias. Plug-in SE is approximate; interval may be wide.",
                physical_shots=ledger.used, shot_budget=instance.shots,
                plan=execution_plan.summary(), experiments=[
                    dict(**entry, mean=means[i], mean_variance=variances[i],
                         term=execution_plan.experiments[i].term,
                         qpd_term=execution_plan.experiments[i].qpd_term,
                         partition=str(execution_plan.experiments[i].partition))
                    for i, entry in enumerate(ledger.entries)],
                execution_seconds=time.perf_counter()-began,
                qiskit_reconstruction_agrees=True)
