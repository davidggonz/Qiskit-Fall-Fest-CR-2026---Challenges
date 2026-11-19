"""Circuit requests and synthetic hardware profiles for Workbook 1."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
from numbers import Integral, Real
from typing import Any
import numpy as np
from qiskit import QuantumCircuit
from qiskit.quantum_info import SparsePauliOp


def _integer(value: Any, name: str, minimum: int, maximum: int | None = None) -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral):
        raise ValueError(f"{name} must be an integer")
    value = int(value)
    if value < minimum or (maximum is not None and value > maximum):
        raise ValueError(f"{name} must be in [{minimum}, {maximum if maximum is not None else 'infinity'}]")
    return value


def _finite(value: Any, name: str, minimum: float, maximum: float) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite real number")
    value = float(value)
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be in [{minimum}, {maximum}]")
    return value


@dataclass(frozen=True)
class HardwareProfile:
    name: str = "ideal"
    topology: str = "line"
    one_qubit_error: float = 0.0
    two_qubit_error: float = 0.0
    readout_error: float = 0.0

    def __post_init__(self):
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("hardware name must be a nonempty string")
        if self.topology not in {"line", "ring", "all_to_all"}:
            raise ValueError("topology must be line, ring, or all_to_all")
        for name in ("one_qubit_error", "two_qubit_error", "readout_error"):
            object.__setattr__(self, name, _finite(getattr(self, name), name, 0, 0.1))

    def edges(self, width: int) -> list[list[int]]:
        width = _integer(width, "width", 1)
        if self.topology == "all_to_all":
            return [[a, b] for a in range(width) for b in range(width) if a != b]
        pairs = [(a, a + 1) for a in range(width - 1)]
        if self.topology == "ring" and width > 2:
            pairs.append((0, width - 1))
        return [[a, b] for a, b in pairs] + [[b, a] for a, b in pairs]


@dataclass
class Instance:
    instance_id: str
    circuit: QuantumCircuit
    observable: SparsePauliOp
    max_width: int
    shots: int
    hardware: HardwareProfile
    seed: int
    family: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        self.max_width = _integer(self.max_width, "max_width", 1)
        self.shots = _integer(self.shots, "shots", 2)
        self.seed = _integer(self.seed, "seed", 0)
        if not isinstance(self.hardware, HardwareProfile):
            raise ValueError("hardware must be a HardwareProfile")
        if self.circuit.num_qubits != self.observable.num_qubits:
            raise ValueError("observable and circuit widths must agree")
        if self.circuit.num_clbits or self.circuit.parameters:
            raise ValueError("input must be a bound circuit without classical bits")
        if not np.all(np.isfinite(self.observable.coeffs)):
            raise ValueError("observable coefficients must be finite")
        if any(abs(x.imag) > 1e-12 for x in self.observable.coeffs):
            raise ValueError("only Hermitian Pauli sums with real coefficients supported")
        if sum(abs(x) for x in self.observable.coeffs) > 1.00000001:
            raise ValueError("normalize sum of absolute Pauli coefficients to <= 1")
        if any(i.operation.name in {"measure", "reset"} for i in self.circuit.data):
            raise ValueError("input circuit must be unitary; fragment resets are generated later")
        for instruction in self.circuit.data:
            for parameter in instruction.operation.params:
                if isinstance(parameter, (Real, complex)) and not np.isfinite(parameter):
                    raise ValueError("circuit gate parameters must be finite")

    def specification(self) -> dict[str, Any]:
        return dict(instance_id=self.instance_id, family=self.family, seed=self.seed,
                    n_qubits=self.circuit.num_qubits, max_width=self.max_width,
                    shots=self.shots, hardware=asdict(self.hardware),
                    observable=[(p, float(c.real)) for p, c in self.observable.to_list()],
                    metadata=self.metadata)
