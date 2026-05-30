# Simulation Step Computation Graph

This document describes the main computation sequence executed by
`SolarCollectorSimulator.step(dt)` in `src/simulation.py`.

## Overview

A single simulation step is a sequential update of the system state:

1. Advance simulation time
2. Update process variables (pump, flow, temperatures)
3. Measure noisy outputs
4. Apply control logic
5. Compute evaluation metrics
6. Record history for later analysis

## Step sequence

### 1. `step(dt)`

The main entry point is `SolarCollectorSimulator.step(dt)`:

- `self.state.simtime += dt`
- `self._process_step(dt)`
- `self._measure_step(dt)`
- `self._control_step(dt)`
- `self._evaluate_step()`
- `self._record_history()`

## 2. `_process_step(dt)`

This is the core process update. It converts the current state and
control targets into new flows and temperatures.

### Pump and valve dynamics

- `state.spumps = pump_speed_update(state.spumpstarg, state.spumps, dt, config.pumptau)`
- `state.valvex = valve_state_update(state.valvextarg, state.valvex, dt, config.valvetau)`

These first-order lag dynamics smooth the pump speed and valve positions
over time.

### Pump head and pressure

- `Fmax, dPpump = pump_head_and_dP(F_total, state.spumps, config.dens)`

This computes the maximum flow and available pump pressure drop from
the total flow and pump speed.

### Flow rate calculation per line

For each of the three collector lines:

- `state.F[line] = flow_rate_from_valve(...)`
- `state.Mdot[line] = config.dens * state.F[line]`

The valve position, pump pressure, and valve sizing determine the flow
for each line.

### Thermal update per line

For each line, `thermal_line_step(...)` advances the fluid and pipe
temperature profile:

- Inputs: `Tb[line]`, `config.initial_Tin`, `state.Mdot[line]`, `config.R`,
  `config.dz`, `dt`, `state.Irad1`, `config.MirrorWidth`, `state.eff1[line]`,
  `config.hamb`, `config.Tamb`, `state.PipeT[line]`, `config.Dispersion`
- Outputs: `Ta_line`, `PipeT_line`
- State updates: `state.Ta[line]`, `state.PipeT[line]`, `state.Tb[line]`

This step is the thermal physics core: fluid convection, pipe heat transfer,
and temperature propagation along the line.

### Aggregate flow state

After all lines are updated:

- `state.Ftotal = np.sum(state.F)`
- `state.Mdottotal = np.sum(state.Mdot)`

These totals feed later control, evaluation, and pump calculations.

## 3. `_measure_step(dt)`

This method generates observed measurements from the updated process state.

- `measured_noise = self.rng.normal(scale=self.config.noise_std, size=3)`
- `state.Fmeas = 0.95 * state.F * (1.0 + measured_noise)`
- `state.T2meas = [exit temperature for each line]`
- `state.T1meas = [exit temperature for each line]`
- `state.Fmeasfilt = 0.9 * state.Fmeas + 0.1 * state.Fmeasfilt`

## 4. `_control_step(dt)`

A placeholder for control logic.

- This is where setpoint adjustment, flow control, or pump control would
  use measurements and model state to update targets such as
  `state.valvextarg` and `state.spumpstarg`.

## 5. `_evaluate_step()`

A placeholder for evaluation and diagnostics.

- This is a good place to compute performance metrics, errors, or any
  derived state used for logging or optimization.

## 6. `_record_history()`

This method appends values to the simulation history:

- `simtime`
- average `T1` and `T2`
- `F_total`
- `pump_speed`

## Recommended documentation location

The best place for this explanation is a dedicated design note in `docs/`.
That keeps the architecture documentation separate from code while still
being easy to browse.

Good options:

- `docs/simulation_step_graph.md` — detailed step-by-step flow
- `README.md` — short pointer to the docs file and a high-level summary
- `src/simulation.py` module docstring — concise overview close to the code

For this repository, a dedicated `docs/` file is the cleanest choice,
with a reference from `README.md` so new contributors can find it quickly.
