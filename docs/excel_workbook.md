# Excel Workbook Reference

**File:** `excel/Solar Collect Model & Control 3 Lines T-T-F 2026-05-01 base case.xlsm`  
**Author:** R. Russell Rhinehart  
**Purpose:** Original VBA-based dynamic simulator and control study for a
3-line parabolic solar collector plant.

The workbook is the reference implementation that the Python/CasADi
reimplementation is derived from.  Macros are archived in `excel/macros/`.

---

## Sheets

### Main

The primary simulation and configuration sheet.

**Configuration area (rows 1–12)** — all model parameters read by
`Initialize()` at the start of each run:

| Column(s) | Contents |
|-----------|----------|
| A–C | Filter/control tuning constants (FOF tau, MBC tau, Flowa filter tau) |
| D–F | Physical plant parameters: MirrorWidth, R, L, dens, Cp, Tamb, hin, hamb, eff, Dispersion |
| G–J | Spatial/temporal grid: dz, N, dt; initial conditions (Tin, TSP); T1 PI gains |
| K–M | Control options (Y/N flags for step changes in valve/eff/TSP/Tin/hamb/Irad); T2 GMC and pump PI gains |
| U–Z | Stochastic disturbance parameters (range and time constants for Irad, T, line-a, optical-eff drifts); noise sigma |

**Simulation output area (rows 14+)** — written by `Output()` during each run.
Each row is one output snapshot (~82 control-interval steps ≈ 87 seconds apart).
Row 14 is the t = 0 initial state.  Columns include:

| Column(s) | Contents |
|-----------|----------|
| A–B | Control error and setpoint for observed line |
| C | Simulation time (hours) |
| D–N | Fluid temperature Tb at segments 1, 10, 20, …, 100 of observed line |
| O | Mixed (flow-weighted average) exit temperature |
| P–R | Segment index and T(k) scatter data |
| S–T | Simulation time and efficiency for observed line |
| U–X | Simulation time, F(LineN), Tin1 |
| AA–AC | DNI, DNI measured, Fdesired, flow pmm |
| AE–AH | Flowa true and estimated |
| AI–AJ | Line dP; valve position |
| AK–AM | Valve dP, line dP, measured line dP, boiler dP |
| AN–AP | T2 model, exit T, pump speed |
| AQ–AT | Valve x, valve target, fofx, fofxm |
| AU–AX | F, Fm (model flow) |
| AY–AZ | hinside at entrance and exit |
| BA–BG | Fmeas, Fmeasfilt (3 lines), Ftotal, Flowa (3 lines), eff (3 lines) |
| BH–BJ | valvex (3 lines) |
| BK–BM | Tb exit (3 lines) |
| BN–BP | Fdesired (3 lines) |
| CG–CI | Fine-grained exit T and mixed T (every 5th output) |

The workbook stored results shown here are from a completed 100-trial Monte
Carlo run (8 simulated hours per trial, t = 8–16 h solar time).

---

### Analysis

Post-processing and statistical analysis sheet for multi-trial Monte Carlo
results.

**Rows 1–6 (summary statistics)** — computed over all trials for each
performance metric:

| Statistic | Description |
|-----------|-------------|
| MAX | Maximum value across trials |
| Average | Mean across trials |
| St Dev | Standard deviation |
| CV on Mean | Coefficient of variation |
| 2.5 sig on mean | 2.5 × standard error of the mean |

**Performance metrics (columns I–Q per trial):**

| Column | Metric |
|--------|--------|
| I | Trial number |
| J | Thermal energy collected (kW-h) |
| K | Pump parasitic energy (kW-h) |
| L | Pump travel (sum of \|Δspumps\|) |
| M | Valve travel (sum of \|Δvalvex\| across 3 lines) |
| N | Exit temperature violation accumulation (C·s above 400 °C) |
| O | Mixed temperature violation accumulation (C below 390 °C) |
| P | Sigma on mixed exit temperature |
| Q | Sigma on line exit temperature |

**Rows 7–106** — one row per trial, columns I–Q filled by `Main()` after each
8-hour run.

**Columns Z–AP** — sorted copies of the trial data, written by `Macro1()`
after all trials complete, used for empirical CDF charts.

**Notes area (column S)** — statistical significance guidance for comparing
two control configurations across 100-trial runs.

---

## Macros

### Module1 — Main simulation engine

This is the core of the simulator.  All state is held in module-level global
arrays and scalars (no explicit state objects).

---

#### `Main()`

Outer Monte Carlo loop.  Runs up to 100 replicate 8-hour simulations
(8 h to 16 h solar time) and writes aggregate trial results to the Analysis
sheet.  Calls `Initialize`, then the inner loop: `Events` → `Process` →
`Measure`/control/`Evaluate`/`Output` at the control interval.

---

#### `Initialize()`

Reads all configuration from the Main sheet cells and sets initial state:

- Reads N, dz, dt, physical params (R, L, dens, Cp, Tamb, hamb, eff,
  Dispersion, Irad), control params, disturbance parameters
- Sets initial temperature profiles: `Tb(k) = 300 + 95k/N` °C,
  `PipeT(k) = 354 + 95k/N` °C (linear ramp from inlet to exit)
- Sets initial flow: `Mdot = 5.63/3` kg/s per line, `F = Mdot/rho(300)`
- Sets all valve targets to 0.9 and pump speed from the sheet cell
- Computes `dt` from the CFL-like stability condition:
  `dt = 0.2 · dz · πR² / F_nominal`

---

#### `Process()`

Core physics timestep.  Advances all state variables by `dt`.

1. **Disturbances** — AR(1) stochastic updates to inlet temperature (`Tin1`),
   irradiance (`Irad1`), per-line optical efficiency (`eff1`), and per-line
   flow-resistance coefficient (`flowa1`) using Box-Muller noise.
2. **Pump speed** — first-order lag: `spumps ← lag(spumpstarg, spumps, dt, pumptau)`
3. **Valve positions** — first-order lag per line, clamped to [0.1, 1.0]
4. **Hydraulic balance** — 10-step successive substitution loop to find
   consistent `Ftotal`, `dPpump`, and `F[i]`:
   - Pump curve: `dPpump = hmax · [1 − (Ftotal/Fmax)^4.347]`
   - System curve: `dPSys = Flowb · Ftotal^1.9`
   - Valve flows: `F[i] = Cv · f(x[i]) · √(dPpump / (G + (dPSys/F[i]² + flowa1[i]/F[i]^0.1) · (Cv·f(x[i]))²))`
   - Convergence criterion: `|ΔFtotal| < 0.01% · Ftotal`
5. **Thermal PDE** — finite-volume explicit Euler update per line for fluid
   temperature (`Ta`) and pipe wall temperature (`PipeT`), then `Tb ← Ta`.

---

#### `Measure()`

Generates noisy measurements from the true state:

- Flow: 5% calibration bias + Box-Muller noise; exponential or SPC filter
- Exit temperatures T1meas (exit), T2meas (mid-line): true values with no
  added noise
- Line pressure drop: 5% bias on `flowa1 · F²`
- Irradiance: 5% bias on true `Irad1`

---

#### `T1Control()` — Primary: PI exit temperature controller

PI controller driving line exit temperature `Ta[N]` to `T1SP`.  Output is a
mid-line temperature setpoint `T2SP[line]`.  Anti-windup via setpoint
clamping to [335, 365] °C.

---

#### `T2Control()` — Secondary: GMC mid-line temperature controller

Generic Model Control (GMC) steady-state law using the estimated optical
efficiency `epsilonest`.  Computes desired flow rate `Fdesired[line]` to
drive mid-line temperature `T2meas` to `T2SP`.  Output is clamped to
[0.001, 0.01] m³/s.

---

#### `FControl()` — Tertiary: model-based valve position controller

Inverts the valve-flow equation to compute the valve stem target
`valvextarg[line]` that achieves `Fdesired[line]`, accounting for a
filtered process-model mismatch term (`Fpmm`).  Uses `dPpump` and current
flow estimates.

---

#### `PumpControl()`

PI controller that adjusts `spumpstarg` to keep the most-open valve near
0.9 (minimises pump parasitic energy while maintaining flow authority).
Asymmetric gain: 5× faster response for "pump too slow" than "pump too fast".

---

#### `Estimate_Coefficients()`

Online parameter estimation at each control interval:

- **Optical efficiency** (`epsilonest`): IMPOL (implicit model-process
  mismatch) gradient update using the steady-state temperature model residual
- **Line pressure-drop coefficient** (`flowaest`): exponential filter on
  `dPLmeas / Fmeas²`
- **Boiler coefficient** (`flowbest`): ratio of boiler/header pressure drop
  to total flow squared (uses sum of filtered flows)

---

#### `Events()`

Applies step changes to the simulation at specified solar times (if the
corresponding Y/N option flags are set on the Main sheet):

- Valve manual step changes (valve open/close events for each line)
- Optical efficiency drops per line
- Exit temperature setpoint ramp
- Inlet temperature step
- Ambient heat loss coefficient change
- DNI step change

---

#### `Output()`

Writes the current simulation state to the next row in the Main sheet output
area.  Called every `outinterval` control intervals (~82 control steps ≈
87 seconds).  Writes temperatures, flows, valve positions, efficiencies,
control signals, and performance metrics.

---

#### `Evaluate()`

Accumulates performance metrics at each control interval:

- ISE on mid-line temperature (`ISE2`) and exit temperature (`ISE1`)
- High exit temperature violation (`Ta[N] > 400 °C`) accumulation
- Low mixed temperature violation (`Tmixed < 390 °C`) accumulation
- Pump and valve travel (sum of absolute changes)
- Pump parasitic energy and total thermal energy collected

---

#### `Tdistribution()`

Copies the final spatial temperature profile from the Main sheet output area
to the Analysis sheet for post-run distribution plotting.

---

#### `FModel()` / `T2modelSub()`

Steady-state model helpers used by the flow and temperature controllers:

- `FModel()`: computes model-predicted flows `Fm[line]` from current valve
  model states and `dPpump`
- `T2modelSub()`: computes steady-state mid-line temperature `T2model[line]`
  from current flow, irradiance, and estimated optical efficiency

---

#### Functions: `rho()`, `rhocp()`, `hinside()`

Fluid property functions used throughout (identical to the Python
implementations in `src/solar_collector/model.py`).

---

### Module2 — Post-run analysis

#### `Macro1()`

Called once after all 100 trials complete.  For each of six performance
metrics (thermal energy, pump energy, pump travel, valve travel, mixed-T
sigma, exit-T sigma), copies the trial data from the results table and sorts
it in ascending order into adjacent columns.  The sorted arrays are used by
chart series to draw empirical CDFs for visual comparison across
configurations.

---

### Sheet1.vba / Sheet2.vba / ThisWorkbook.vba

Empty module stubs — contain only the VB class attribute declarations for the
Main sheet, Analysis sheet, and Workbook objects respectively.  No event
handlers or custom sheet code.

---

## Key design notes

- **Global mutable state** — all simulation variables are module-level globals
  in Module1.  There are no classes or explicit state containers.
- **Worksheet as database** — configuration is read from specific hard-coded
  cell addresses on every `Initialize()` call.  The sheet is also the output
  buffer, display, and chart data source simultaneously.
- **10-step successive substitution** — the hydraulic balance (pump pressure
  vs. valve flows) is resolved by iteration rather than a formal solver.
  The Python reimplementation replaces this with a CasADi Newton rootfinder.
- **4-level cascade control** — primary PI (exit T → T2 setpoint) → secondary
  GMC (mid T → Fdesired) → tertiary MBC (Fdesired → valve target) → pump
  PI (max valve → pump speed).
- **Monte Carlo capability** — `Main()` loops up to 100 times with different
  random seeds, writing aggregate results to the Analysis sheet for
  statistical comparison of controller configurations.
