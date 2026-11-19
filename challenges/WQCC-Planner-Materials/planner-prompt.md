# Workbook 1 · Cut and reconstruct

This guide accompanies [01_cut_and_reconstruct.ipynb](01_cut_and_reconstruct.ipynb). The wider WQCC challenge asks teams to plan quantum circuit execution under hardware and sampling limits. Workbook 1 studies one concrete gate cut and one observable so you can explain the reconstruction and resource tradeoffs before making broader claims.

## Start with Workbook 1

[01_cut_and_reconstruct.ipynb](01_cut_and_reconstruct.ipynb) is the only workbook in this package. Allow 90–120 minutes for its eight exercises and discussion. Follow its setup instructions or the [Python guide](python/README.md), then run cells in order. The exercise answers are intentionally blank.

The notebook follows one four-qubit circuit with an RZZ interaction between two two-qubit fragments. It shows how the cutting add-on generates six signed recipe pairs and twelve physical experiment settings. You will reconstruct one Z correlation, account for every shot, interpret sampling uncertainty, and compare direct execution with cutting after making direct execution feasible under a wider limit.

## What this example establishes

The local simulation checks reconstruction against an ideal statevector answer and a closed-form answer for this specific circuit. It also illustrates how a fixed physical-shot budget is shared across fragment experiments. The circuit is classically tractable and provides no evidence of quantum advantage or general planner performance. Four repetitions in one matched comparison illustrate variation; they do not support broad method rankings.

A planner may execute a circuit directly when it fits or cut it into smaller experiments. Cuts introduce local recipes, signed coefficients, and possible sampling overhead. A cut plan must preserve the requested observable; deleting the boundary gate changes the question. The notebook uses gate cutting, synthetic local noise, and one target observable. Wire cutting and multiple-target planning are outside this workbook.

The reported interval describes sampling uncertainty for the reconstructed noisy quantity under fixed allocation. It does not bound noise bias against the ideal answer. Diagnostic ideal values are for checking results after execution, not for choosing a plan.

## What to keep

Save your completed notebook and its generated recipe table, signed contribution table, physical-shot ledger, and matched comparison if completed. Explain the width limit, the total shot allowance, how recipe signs enter the estimate, and what the comparison does and does not show. Use the event organizers' final submission instructions when available.

## Optional references for this workbook

- [Qiskit gate-cutting tutorial](https://qiskit.github.io/qiskit-addon-cutting/tutorials/01_gate_cutting_to_reduce_circuit_width.html): partitioning and reconstruction.
- [Exact sampling coefficients](https://qiskit.github.io/qiskit-addon-cutting/how-tos/how_to_generate_exact_sampling_coefficients.html): exact recipe weights with finite-shot measurements.
- [Cutting decomposition implementation](https://qiskit.github.io/qiskit-addon-cutting/_modules/qiskit_addon_cutting/qpd/decompositions.html): coefficient and experiment pairing used by the notebook.
- [Qiskit RZZ definition](https://quantum.cloud.ibm.com/docs/en/api/qiskit/qiskit.circuit.library.RZZGate): angle and sign convention.
- [Qiskit bit ordering](https://quantum.cloud.ibm.com/docs/en/guides/bit-ordering): Pauli labels and measured bits.

## Credits and source material

- **Challenge framing:** UW–Madison WQCC’s *Official Sponsored Prompt*, included with the original planner materials, supplied the broader challenge and Explorer track context.
- **Circuit cutting:** The [Qiskit circuit-cutting explanation](https://qiskit.github.io/qiskit-addon-cutting/explanation/), [gate-cutting tutorial](https://qiskit.github.io/qiskit-addon-cutting/tutorials/01_gate_cutting_to_reduce_circuit_width.html), [exact-coefficient guide](https://qiskit.github.io/qiskit-addon-cutting/how-tos/how_to_generate_exact_sampling_coefficients.html), and [decomposition implementation](https://qiskit.github.io/qiskit-addon-cutting/_modules/qiskit_addon_cutting/qpd/decompositions.html) informed the partitioning, local recipes, and reconstruction. The workbook uses Qiskit addon: circuit cutting 0.10.0.
- **Qiskit conventions:** IBM Quantum’s [RZZGate reference](https://quantum.cloud.ibm.com/docs/en/api/qiskit/qiskit.circuit.library.RZZGate) and [bit-ordering guide](https://quantum.cloud.ibm.com/docs/en/guides/bit-ordering) support the gate-sign and Pauli-label explanations.
- **Local noise simulation:** The [Qiskit Aer noise-model tutorial](https://qiskit.github.io/qiskit-aer/tutorials/3_building_noise_models.html) documents the gate and readout error tools used in the supporting code.
- **Foundational research:** Kosuke Mitarai and Keisuke Fujii, [*Constructing a virtual two-qubit gate by sampling single-qubit operations*](https://arxiv.org/abs/1909.07534v2), and [Peng et al., *Simulating Large Quantum Circuits on a Small Quantum Computer*](https://arxiv.org/abs/1904.00102v2), provide background for reconstructing larger-circuit observables from smaller experiments.

The circuit, exercise prompts, plots, and tables in this workbook are prepared within these materials. The plots and tables are generated by the notebook code.
