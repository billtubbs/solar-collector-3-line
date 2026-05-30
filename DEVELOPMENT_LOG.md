# Development Log

## 2026-05-30

### Completed
- Created `pyproject.toml` with runtime dependencies and developer extras.
- Added a minimal `README.md` describing install/test instructions.
- Added `tools/extract_vba.py` to extract VBA macros from the `.xlsm` workbook.
- Installed `oletools` and `openpyxl` in the project venv.
- Extracted macros from `excel/Solar Collect Model & Control 3 Lines T-T-F 2026-05-01 base case.xlsm` into `excel/macros/`:
  - `Module1.vba`
  - `Module2.vba`
  - `Sheet1.vba`
  - `Sheet2.vba`
  - `ThisWorkbook.vba`
  - `index.txt`
- Inspected the workbook and found:
  - `Main` sheet contains ~100 formula cells and ~22,760 value cells.
  - `Analysis` sheet contains ~1,164 formula cells and ~1,827 value cells.
- Reorganised source into a proper `src`-layout package at `src/solar_collector/`:
  - `src/solar_collector/__init__.py`
  - `src/solar_collector/model.py` — pure Python physics functions derived from `Module1.vba`
  - `src/solar_collector/simulation.py` — `SimulationConfig`, `SimulationState`, `process_step`, and `SolarCollectorSimulator`
  - `src/solar_collector/casadi_model.py` — `CasadiSolarCollectorModel`, a CasADi discrete-time state-space model
- Fixed `pyproject.toml` to use `[tool.setuptools.packages.find] where = ["src"]` so the package is correctly discovered under the `src` layout.
- Added `tests/test_data.yml` with workbook-derived regression inputs and expected outputs.
- Added `tests/test_model.py`; fixed a path bug (`Path("tests")` → `Path(__file__).parent`, `yaml.safe_load(path)` → `yaml.safe_load(path.read_text())`).
- Added `tests/test_casadi_model.py`; fixed CasADi 3.7 calling convention: a single-output `Function` returns its DM result directly, not wrapped in a list, so `model.F(...)[0]` and `model.H(...)[0]` were corrected to `model.F(...)` and `model.H(...)`.
- Reviewed and rewrote `casadi_model.py` for correctness and CasADi idiom:
  - Promoted `_casadi_rho` and `_casadi_hinside` to module-level functions (were buggy lambdas — the lambda keyword-argument defaults were silently overridden by hardcoded values in the body).
  - Replaced `Tb[:, -1]` (unreliable negative indexing in CasADi) with `Tb[:, self.N - 1]`.
  - Replaced SX item-assignment pattern (`Tb_new[line, :] = Ta_line`) with `cas.vertcat(*Tb_rows)`.
  - Replaced hardcoded `F_lines[0] + F_lines[1] + F_lines[2]` with `cas.sum1(F_lines)`.
  - Removed `sqrt=cas.sqrt` passed to `pump_head_and_dP` (that function does not use `sqrt`).
  - Introduced `offset` variable in `_unpack_state` to eliminate repeated magic index expression.
- Verified `13 passed` with pytest (11 model tests + 2 CasADi model tests).

### Design notes
- `model.py` injects all math operations (`exp`, `log`, `sqrt`, `min`, `max`, `pi`) as keyword arguments so the same physics functions run under NumPy (simulation) and CasADi (optimisation/control) without duplication.
- `CasadiSolarCollectorModel` mirrors the attribute interface of `StateSpaceModelDT` in the `casadi-models` package (duck-type compatibility without a hard dependency).
- `Module1.vba` is highly monolithic and stateful; it relies on module-level global arrays and many direct `Cells(...)` references.
- The `Main` worksheet is not purely input/output; it contains formula-based helper calculations that contribute to the simulation configuration.
- `Analysis` contains post-processing and reporting formulas, while `Module2.vba` is mainly sorting/copying results for reporting.
- The VBA `hinside` function uses global `F(LineN)` state and `R`; refactored into an explicit function of line flow and geometry.
- The `Process` routine uses successive substitution for the pump/line flow interaction; should become an explicit numerical solver or algebraic update.
- Measurement and control logic in the VBA code depend on workbook option cells and manual/auto flags.
- `Estimate_Coefficients` uses filtered estimates and model parameter updates; should be separated from the core physical model.
- Several numeric magic constants are embedded in the VBA code and should be moved into named configuration fields.

### Discrepancies / improvements still to address
- `simulation.py` is a working first draft but is considered a placeholder — it will be redesigned.
- Centralise sheet-to-parameter mapping.
- Decouple physics from control.
- Preserve units clearly and avoid hidden Excel-dependent state.
- Expand tests to cover edge cases and boundary conditions.
- `flowaest` (estimated line flow) is a state variable in `simulation.py` but is hardcoded to `0.0` in `CasadiSolarCollectorModel`; the numerical impact is negligible but the asymmetry should be resolved when the state vector is finalised.

### Next actions
- Redesign and rewrite `src/solar_collector/simulation.py` as the main simulation driver, based on the step sequence in `docs/simulation_step_graph.md`.
- Build a Gymnasium environment wrapper around `SolarCollectorSimulator`.
