# Development Log

## 2026-05-30

### Completed
- Created `pyproject.toml` with runtime dependencies and developer extras.
- Added a minimal `README.md` describing install/test instructions.
- Added `tools/extract_vba.py` to extract VBA macros from the `.xlsm` workbook.
- Installed `oletools` and `openpyxl` in the project venv.
- Extracted macros from `excel/Solar Collect Model & Control 3 Lines T-T-F 2026-05-01 base case.xlsm` into `excel/macros/`:
  - `Module1.vba`, `Module2.vba`, `Sheet1.vba`, `Sheet2.vba`, `ThisWorkbook.vba`, `index.txt`
- Inspected the workbook:
  - `Main` sheet: ~100 formula cells, ~22,760 value cells (simulation output), ~282 output rows at ~87 s intervals.
  - `Analysis` sheet: ~1,164 formula cells, ~1,827 value cells (Monte Carlo trial results).
- Reorganised source into `src/solar_collector/` package; fixed `pyproject.toml` for `src` layout.
- Added `tests/test_data.yml`, `tests/test_model.py`, `tests/test_casadi_model.py` with regression tests.
- Fixed CasADi 3.7 calling convention bugs in tests; rewrote `casadi_model.py` for correctness and CasADi idiom.
- **Added CasADi Newton rootfinder** to `CasadiSolarCollectorModel` (`_build_flow_balance_solver`):
  - Replaces the open-loop approximation that used the previous step's `Ftotal`.
  - Replaces the VBA's 10-step successive-substitution loop for the pump/valve hydraulic balance.
  - Finds `Ftotal*` such that `∑ F_i(valvex_i, ΔP_pump(Ftotal*, s)) = Ftotal*` at each step.
  - CasADi's automatic differentiation provides the Newton Jacobian at no extra cost.
- Updated `test_casadi_model.py`:
  - Replaced the single comparison-against-`process_step` test with two focused tests.
  - `test_casadi_model_step_pump_valve_dynamics`: validates pump/valve lag against pure Python.
  - `test_casadi_model_hydraulic_balance`: verifies the rootfinder yields a self-consistent solution.
  - 14 tests total, all passing.
- Added full class docstring to `CasadiSolarCollectorModel` listing all state, input, and output variables with units.
- **Documentation:**
  - Added `docs/solar_collector_model.md` (replaces `docs/simulation_step_graph.md`): full LaTeX
    equations with nomenclature table, covering fluid properties, heat transfer, valve characteristic,
    pump curve, hydraulic balance rootfinder, actuator lags, pipe wall temperature, finite-volume
    PDE, state-space summary, and simulation step sequence.
  - Added `docs/excel_workbook.md`: comprehensive reference for both sheets and all VBA macros
    (sub-routine descriptions, equations, design notes).
  - Updated `README.md` with project purpose, objectives, repo layout, and documentation pointer.
- Configured `.vscode/settings.json` for format-on-save using `ruff format` for Python files.
- **Added `src/solar_collector/casadi_controllers.py`** — four CasADi discrete-time controllers,
  all mirroring the `StateSpaceModelDT` interface:
  - `ControllerConfig` — dataclass with defaults matching the base-case spreadsheet.
  - `T1PIController` — primary PI exit-temperature controller; state: `Iterm[1..3]`;
    output: `T2SP[1..3]`; anti-windup via back-calculated integral.
  - `T2GMCController` — secondary GMC mid-line temperature controller; state: `GMCbias[1..3]`;
    output: `Fdesired[1..3]`; bias updated with exponential filter on SS model–setpoint mismatch.
  - `FMBCController` — tertiary model-based valve controller; state: `[valvexm[1..3], Fpmm[1..3]]`;
    output: `valvextarg[1..3]`; inverts valve equation with flow mismatch correction.
  - `PumpPIController` — auxiliary pump speed controller; state: `[pumpintegral]`;
    output: `[spumpstarg]`; asymmetric gain (5× faster to speed up than slow down).
- **Redesigned `src/solar_collector/simulation.py`**:
  - Removed `SolarCollectorSimulator` class and old step functions (`process_step`,
    `measure_step`, `control_step`, `evaluate_step`, `record_history`).
  - Added `simulate(plant, controller, nT, nd, measurement_fn)`: builds and returns a CasADi
    Function with signature `(t_eval, D, x0) → (X, Y)` for closed-loop n-step simulation.
    `D` is the disturbance/exogenous input matrix; `x0` is the concatenated initial state
    `[x_plant; x_ctrl]`; `X` and `Y` are the combined-state and plant-output trajectories.
  - Added `make_open_loop_simulation(plant, nT)`: open-loop equivalent with signature
    `(t_eval, U, x0) → (X, Y)`, matching `make_n_step_simulation_function_from_model` from
    the `casadi-models` package.
  - Kept `SimulationConfig` and `SimulationState` for backward compatibility with existing tests.
- **Added `run_simulation_ol.py`** — open-loop simulation script using
  `make_open_loop_simulation`:
  - Single plant model (`CasadiSolarCollectorModel`) with fixed irradiance.
  - Pump speed step change (`SPUMP_NOMINAL → SPUMP_STEPPED`) at step
    `T_STEP_K`; step must fall on a chunk boundary so only one CasADi
    simulation function is needed.
  - Flow rates initialised via `plant.flow_balance` (the hydraulic Newton
    rootfinder) rather than a density-based heuristic, eliminating a
    spurious transient at t = 0.
  - Saves results to `results/simulation_ol.npz` and `results/simulation_ol.csv`
    (inputs, states, outputs at every `N_CHUNK` steps).
  - Produces four-panel time-series plots (temperatures, flow rates, valve
    positions, pump speed) via `plot_utils.make_tsplots`.
- **Added `plot_utils.py`** — lightweight Matplotlib helpers:
  - `make_tsplots(t, plot_data, ...)`: stacked subplots from a dict of
    named panels; supports `"plot"` and `"step"` trace kinds.
  - `make_ioplots(t, inputs, states, outputs, ...)`: convenience wrapper
    that organises outputs, states, and inputs into labelled panels.

### Design notes
- `model.py` injects all math operations (`exp`, `log`, `sqrt`, `min`, `max`, `pi`) as keyword
  arguments so the same physics functions run under both NumPy and CasADi without duplication.
- `CasadiSolarCollectorModel` and all four controllers mirror the attribute interface of
  `StateSpaceModelDT` in the `casadi-models` package (duck-type compatible, no hard dependency).
- The four VBA controllers form a 4-level cascade: T1PI → T2GMC → FMBC → plant, with PumpPI
  running in parallel to keep the most-open valve near 0.9.
- The `simulate` function requires `controller.ny == plant.nu` (= 4 for this plant); individual
  cascade controllers must be composed into a single combined controller before use.
- The Excel workbook stores simulation output at ~87-second intervals (355 physics timesteps).
  Stored data is insufficient for full `F(t, x, u)` validation because: (1) plant state is
  partial (one of three lines, 10 of 100 segments, no PipeT); (2) control inputs are not stored
  between snapshots; (3) stochastic disturbances are irreproducible. The hydraulic balance
  (spumps + valvex[1..3] → Ftotal across 282 snapshots) is a feasible isolated validation target.
- `PumpControl` in the VBA integrates using `dt` (physics timestep, ~0.246 s) rather than the
  control interval (1 s). The Python `PumpPIController` uses `dt_ctrl` (the correct control
  interval); tuning of `PumpPIGain` / `PumpPITau` may need adjustment to match VBA behaviour.

### Discrepancies / improvements still to address
- Hydraulic balance validation against 282 stored spreadsheet snapshots not yet implemented.
- Controller cascade composition into a single `StateSpaceModelDT`-compatible model not yet
  implemented; needed before `simulate` can be used with the full cascade.

### Next actions
- Validate the hydraulic balance against stored spreadsheet snapshots.
- Compose the cascade controllers into a single combined controller.
- Write a `simulate` end-to-end test using the full cascade.
- Build a Gymnasium environment wrapper.

---

## 2026-05-31

### Completed

- **Removed volumetric flow rates from the state vector** (`casadi_model.py`):
  - `F1..3` eliminated; state is now `n = 1 + 2·n_lines + 2·n_lines·N` (was `1 + 3·n_lines + ...`).
  - Hydraulic balance now initialised from `Mdot / dens` rather than the stored `F` values.
  - Volumetric flow at any axial position can be recovered post-hoc as `F_i(k) = Mdot_i / rho(Tb_i_k)`.
  - Updated `_unpack_state`, `_pack_state`, `_state_update`, and `_output_map` accordingly.
  - Moved `plot_utils.py` → `src/plot_utils.py`.
  - Updated `run_simulation_ol.py` and `tests/test_casadi_model.py` to match new state layout.

- **Added disturbance inputs to model interface** (`casadi_model.py`):
  - `Irad`, `Tamb`, and `Tin` promoted from hardcoded config fields to runtime inputs in the `u` vector.
  - Input vector is now `nu = 1 + n_lines + 3`; `input_names` extended with `["Irad", "Tamb", "Tin"]`.
  - `_unpack_input` now returns `spumpstarg, valvextarg, Irad, Tamb, Tin`.
  - `_state_update` passes live `Irad`, `Tamb`, `Tin` to `thermal_line_step` each step.
  - Output vector redesigned: `y = [Mdot1..3, Tb{i}_{k}]` (all mass flows then full temperature field); exit temperatures are the last-segment rows.
  - Updated `run_simulation_ol.py` and tests to supply disturbances explicitly.

- **Added real-time animated live simulation** (`src/solar_collector/live_sim.py`, `run_simulation_live.py`):
  - `SolarCollectorLiveSim` class drives a `matplotlib.animation.FuncAnimation` loop.
  - Each frame advances the plant by `steps_per_frame` CasADi steps, appends to rolling deque buffers, and redraws all artists.
  - **Layout**: two spatial-profile subplots (fluid temperature and pipe-wall temperature vs axial position) and five scrolling time-series subplots (exit temperatures, mass flow rates, pump speed actual + target, solar irradiance, valve positions).
  - **Interactive sliders**: pump speed target, valve 1–3 targets, `Irad`, `Tamb`, `Tin`; slider callbacks write directly to `self.u` so changes take effect on the next step.
  - **Start/Stop button**: pauses/resumes `FuncAnimation`; label toggles between `"STOP"` and `"START"`.
  - **Time counter**: monospace `"t = NNN.N s"` label updated every frame.
  - `run_simulation_live.py`: entry-point script that builds `SimulationConfig` and `CasadiSolarCollectorModel`, initialises `x0` via the hydraulic Newton rootfinder, and calls `SolarCollectorLiveSim.run()`.

- **Added Lagrangian flow-marker particles** to the spatial profile plots (`live_sim.py`):
  - 10 tracer particles per line rendered as `"|"` tick marks on both the fluid-temperature and pipe-wall-temperature profiles.
  - Particles advect each frame using the local fluid velocity `v = Mdot / (rho(Tb) · A_pipe)`, interpolated at each particle's axial position.
  - Wrap-around at collector exit so particles re-enter at the inlet.
  - Initial positions staggered by `1/n_lines` of the inter-marker spacing so markers from different lines don't coincide at `t = 0`.

### Next actions
- Validate the hydraulic balance against stored spreadsheet snapshots.
- Compose the cascade controllers into a single combined controller.
- Write a `simulate` end-to-end test using the full cascade.
- Build a Gymnasium environment wrapper.

---

## 2026-06-06

### Completed

- **Refactored live simulation layout** (`live_sim.py`):
  - Resized figure from 12×11 to 16×8 (landscape format for widescreen display).
  - Reorganised `GridSpec` from 4 rows × 3 columns to 2 rows × 4 columns with `height_ratios=[1.8, 1.0]`.
  - Merged the two separate spatial-profile subplots (fluid `ax_tb` and pipe-wall `ax_pt`) into a single combined subplot (`ax_profile`): fluid lines solid, pipe-wall lines dashed on the same axes.
  - Removed pipe-wall Lagrangian flow markers (`_pt_particle_markers`); flow markers now appear on the fluid temperature profile only.
  - Reorganised the bottom time-series row into four equal columns: irradiance | valve positions | pump speed | line flow rates.
  - Renamed "Exit fluid temperatures" → "Fluid inlet and exit temperatures" (subplot already included `Tin`).
  - Renamed "Mass flow rates" → "Line flow rates".
  - Added layout diagram to module docstring.
  - Simplified `_build_sliders` signature (removed unused `slider_zone` parameter).

- **Minor model.py tidying** (`model.py`):
  - Grouped `DEFAULT_PI` and `ZERO_CELSIUS` at the top of the file under a *Universal constants* comment.
  - Added a comment clarifying that `DEFAULT_*` math-function variables allow the same physics code to run under both NumPy and CasADi.

- **Live simulation plot refinements** (`live_sim.py`):
  - Reduced pipe-wall temperature profile line width from 1.5 to 1.0 so dashed lines are less visually dominant.
  - Reduced flow marker height and line width (ms: 10 → 7, mew: 1.5 → 1.0).
  - Reduced vertical spacing between plot rows (hspace: 0.55 → 0.35).
  - Synchronised y-axis range of both temperature subplots: fixed maximum 450 °C, auto minimum 5 °C below the lowest data point in either plot; updated on every animation frame.
  - Added a 400 °C maximum temperature limit as a dark-grey dashed horizontal line to both temperature subplots, with a legend entry "T max (400°C)".
  - Swapped pump speed and valve positions subplots (pump now column 1, valve now column 2 in the bottom row).
  - Coloured valve sliders to match their per-line plot colours (tab:blue / tab:orange / tab:green): both the slider bar fill and the label text are coloured and bold.

- **Added `make_initial_state` helper** (`model.py`):
  - `make_initial_state(plant, T_init, spump=0.0, valvex=0.1, Mdot=0.0)` constructs a uniform initial state vector; all fluid and pipe-wall segments set to `T_init`, actuator states from the remaining parameters.
  - Simplifies `run_simulation_live.py` x0 construction from ~20 lines (linear ramp + hydraulic solve) to a single call.

- **Ambient cold-start initial conditions** (`run_simulation_live.py`):
  - Default start changed to all temperatures at `cfg.Tamb`, pump and valves at their minimums, irradiance zero (pre-sunrise).

- **Named actuator limits** (`live_sim.py`):
  - Added module-level constants `_PUMP_MIN = 0.3`, `_PUMP_MAX = 1.0`, `_VALVE_MIN = 0.1`, `_VALVE_MAX = 1.0`; wired into slider specs so the slider range and initial conditions share a single source of truth.
  - `run_simulation_live.py` imports `_PUMP_MIN` / `_VALVE_MIN` directly so startup state matches slider floor.

- **Fixed NaN in hydraulic solver at low pump speed** (`model.py`, `casadi_model.py`):
  - `pump_head_and_dP`: added `max=DEFAULT_MAX` parameter; denominator `Fmax` is now clamped to `max(Fmax, 1e-10)` before dividing, eliminating the `0/0 → NaN` when `spumps ≈ 0`. Both CasADi call sites updated to pass `max=_casadi_max`.

- **Further live simulation refinements** (`live_sim.py`, `run_simulation_live.py`):
  - Increased padding between the lower plot row and the slider area (`bottom` offset raised).
  - Irad slider: added a nominal reference marker at 0.95 kW/m² (noon peak from VBA DNI model) so the red line sits at the operating point even when the slider starts at zero; actual init value and slider handle remain at `IRAD_INIT`.
  - Initial valve positions changed to fully open (`VALVE_INIT = _VALVE_MAX = 1.0`).
  - Tin and Tamb slider lower bounds lowered to 10 °C to match the ambient cold-start initial condition.
  - Frame interval corrected to 246 ms (`≈ dt × 1000`) so the simulation runs at real time (~4 fps) instead of the previous 5× real-time rate.
  - `_update_temp_ylim` helper added: `set_ylim` is now only called when the lower bound changes by more than 2 °C, eliminating the full layout recalculation on every frame that was degrading slider responsiveness.
  - Pump speed y-axis lower bound set to `_PUMP_MIN − 0.05 = 0.25` so the 0.3 minimum is visually prominent.
  - Irradiance y-axis lower bound set to −0.05 so the zero line is clearly visible.
  - **Fast-forward button** (`+15 s`) added to the slider area, to the left of the STOP/START button. Clicking sets `_ff_steps = round(15.0 / dt)` (~61 steps); the flag is drained on the next animation frame with per-step `_record()` calls so the history buffers capture the full trajectory.
  - Removed type annotations from `make_initial_state` in `model.py` for consistency with the rest of the file.

- **Temperature plot reference lines and named constants** (`live_sim.py`):
  - Added module-level constants `_T_PLOT_MAX = 475`, `_T_MAX = 400`, `_T_SP = 395`.
  - Both temperature subplots now show a red dashed `T_SP` line at 395 °C and a dark-grey dashed `T max` line at 400 °C.
  - Y-axis maximum raised from 450 °C to 475 °C to provide space above the safety limit line for the legend.
  - All magic numbers in ylim and axhline calls replaced with the named constants.

- **Corrected hydraulic balance to match VBA plant simulation** (`model.py`, `casadi_model.py`, `tests/test_casadi_model.py`):
  - Root cause: `flow_rate_from_valve` implemented the *controller's simplified model* (VBA line 390, using `flowaest + 9·Flowb` constant) instead of the *plant simulation* equation (VBA line 540, `dPSys/F² + flowa1/F^0.1`). There was no documented reason for this deviation.
  - Added `line_pressure_balance_residual(F_line, Ftotal, fofx, Cv, G, Flowa, Flowb, dPpump)` to `model.py`: encapsulates the correct per-line pressure balance `dP_valve + dP_line + dP_system = dP_pump` where `dP_line = Flowa·F^1.9` and `dP_system = Flowb·Ftotal^1.9`. Works with both NumPy and CasADi SX via the `**` operator.
  - Replaced the 1-variable rootfinder (`z = Ftotal`) with a 4-variable Newton solver (`z = [Ftotal, F_1, F_2, F_3]`) using one flow-conservation equation and three per-line pressure-balance equations. `Flowa` (already in `SimulationConfig`) is now used correctly.
  - A `1e-6` floor on the initial guess prevents a singular Jacobian in `F^1.9` at cold-start zero flow.
  - Simplified `_state_update`: the redundant `pump_head_and_dP` + `flow_rate_from_valve` calls after the rootfinder are removed; `F_lines_new` comes directly from solver output `z_sol[1:]`.
  - Updated `test_casadi_model_hydraulic_balance` to verify each line's pressure-balance residual is zero rather than re-checking the old simplified equation. All 14 tests pass.

### Discrepancies to investigate
- **Pump speed minimum discrepancy**: VBA (`Module1.vba` line 218) clips `spumpstarg ≥ 0.3`; valve minimum in VBA is 0.1 (lines 363–364, 388, 515). The Python `_PUMP_MIN = 0.3` has been set to match the VBA. The original reason for the 0.3 floor (vs a lower value like 0.1) is not documented in the VBA — **to be clarified with the workbook author**.

### Next actions
- Validate the hydraulic balance against stored spreadsheet snapshots.
- Compose the cascade controllers into a single combined controller.
- Write a `simulate` end-to-end test using the full cascade.
- Build a Gymnasium environment wrapper.
