# Python support for Workbook 1

This folder contains the files needed for [01_cut_and_reconstruct.ipynb](../01_cut_and_reconstruct.ipynb). The notebook builds one four-qubit circuit, cuts its boundary interaction into two-qubit experiments, reconstructs an observable, and compares plans under a fixed shot budget.

## Set up

Keep the notebook, this `python` folder, and [planner-prompt.md](../planner-prompt.md) together. Python 3.12 is recommended. From the folder containing the notebook, run:

Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r python/requirements.txt
.\.venv\Scripts\python.exe python/check_environment.py
.\.venv\Scripts\python.exe -m jupyterlab
```

macOS or Linux:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r python/requirements.txt
.venv/bin/python python/check_environment.py
.venv/bin/python -m jupyterlab
```

Open `01_cut_and_reconstruct.ipynb`, select the environment's kernel, and run cells in order. Installation needs internet; the exercises use local simulation and require no IBM account. The notebook creates `results/01-cut-and-reconstruct/` when its sampling cell runs.

## Files

| File | Purpose |
|---|---|
| `requirements.txt` | Pinned dependencies for the notebook. |
| `check_environment.py` | Checks imports, circuit compilation, and a short Aer simulation. |
| `wqcc_planner/instances.py` | Defines the circuit request and hardware profile used by the notebook. |
| `wqcc_planner/engine.py` | Prepares direct or cut plans, samples experiments, and reconstructs the observable. |
| `wqcc_planner/statistics.py` | Allocates shots and computes uncertainty summaries. |

The engine also retains its automatic-cut planning path, although Workbook 1 uses the direct and structured-cut modes. Workbook 1 makes its teaching circuit in the notebook.

## Troubleshooting

- If an import fails, check `sys.executable` in a notebook cell and select the kernel from the environment above.
- If you change a Python support file, restart the kernel before rerunning the notebook.
- `Pending` exercise checks mean that the response slots are deliberately blank. The worked examples run independently.
- A four-qubit direct plan fails the notebook's two-qubit width limit by design. The later matched comparison raises the width limit to four.

The example is small enough for classical statevector checks. Its sampling interval describes the reconstructed noisy quantity under fixed allocation; it does not bound hardware bias against the ideal answer.
