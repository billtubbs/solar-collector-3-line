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
- Created `src/model.py` with pure Python functions derived from `Module1.vba`.
- Verified the new module imports and basic calculations successfully.
- Added `tests/test_data.yml` with workbook-derived regression inputs and expected outputs.
- Added `tests/test_model.py` and verified `11 passed` with pytest for `src/model.py`.

### Discrepancies / Notes / Improvements
- `Module1.vba` is highly monolithic and stateful; it relies on module-level global arrays and many direct `Cells(...)` references.
- The `Main` worksheet is not purely input/output; it contains formula-based helper calculations that contribute to the simulation configuration.
- `Analysis` contains post-processing and reporting formulas, while `Module2.vba` is mainly sorting/copying results for reporting.
- The VBA `hinside` function uses global `F(LineN)` state and `R`; this should be refactored into an explicit function of line flow and geometry.
- The `Process` routine uses successive substitution for the pump/line flow interaction; that should become an explicit numerical solver or algebraic update in Python.
- Measurement and control logic in the VBA code depend on workbook option cells such as `Cells(12, 9)` and manual/auto flags.
- `Estimate_Coefficients` uses filtered estimates and model parameter updates; this should be separated from the core physical model.
- Several numeric magic constants are embedded in the VBA code and should be moved into named configuration fields.
- Improvements to implement next:
  - centralize sheet-to-parameter mapping
  - decouple physics from control
  - build pure numeric primitives first, then layer the control sequence
  - preserve units clearly and avoid hidden Excel-dependent state

### Next action
- Begin building the Python simulation driver in `src/simulation.py`, based on the VBA step sequence and the pure model primitives in `src/model.py`.
