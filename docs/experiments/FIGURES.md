# Regenerate thesis figures and tables

> AI-generated documentation.

This repository provides the models and raw-data reader. The plotting and
LaTeX scripts are in the **separate thesis-source repository**. Keep this layout:

```text
ropeway/
  ropeway_skip_stop_optimization/   # this repository, with results/ extracted
  idp_report/version_2/            # thesis sources, including scripts/ and Makefile
```

From the optimization repository root, install the pinned analysis dependencies:

```sh
uv sync --frozen --extra analysis
python3 benchmarks/verify_submission.py
cd ../idp_report/version_2
../../ropeway_skip_stop_optimization/.venv/bin/python scripts/plot_relative_journey_results.py
../../ropeway_skip_stop_optimization/.venv/bin/python scripts/plot_constant_journey_results.py
../../ropeway_skip_stop_optimization/.venv/bin/python scripts/plot_journey_stop_skip.py
../../ropeway_skip_stop_optimization/.venv/bin/python scripts/export_journey_model_sizes.py
../../ropeway_skip_stop_optimization/.venv/bin/python scripts/verify_oip_service_contract.py
../../ropeway_skip_stop_optimization/.venv/bin/python scripts/export_oip_appendix.py
../../ropeway_skip_stop_optimization/.venv/bin/python scripts/export_oip_model_sizes.py
../../ropeway_skip_stop_optimization/.venv/bin/python scripts/plot_service_results.py
```

These commands regenerate derived CSVs, tables and figures without optimization.
They retain the frozen result selection and do not modify raw solver evidence.
The commands use the macOS/Linux virtual-environment layout.

For the PDF, run `make pdf` from `idp_report/version_2/`. This additionally needs
`make`, `latexmk` and a LaTeX installation with the packages used by the thesis
(e.g. TeX Live). The output is `build/main.pdf`.

Return to the [experiment guide](README.md) for new solver runs, or the
[reviewer guide](../REVIEWER_GUIDE.md) for interpretation and validation scope.
