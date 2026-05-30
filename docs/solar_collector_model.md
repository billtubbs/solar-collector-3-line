# Solar Collector Plant Model

This document describes the mathematical model of the 3-line parabolic solar
collector plant, its discrete-time state-space formulation, and the simulation
step sequence.  The Python implementation lives in
`src/solar_collector/model.py`, `src/solar_collector/casadi_model.py`, and
`src/solar_collector/simulation.py`.

---

## Nomenclature

| Symbol | Python variable | Description | Units |
|--------|----------------|-------------|-------|
| $T$ | `localT` | Fluid temperature | °C |
| $T_K$ | `localTK` | Fluid temperature (Kelvin) | K |
| $\rho$ | `rho` | Fluid density | kg/m³ |
| $C_p$ | `fluid_Cp` | Specific heat capacity | kJ/(kg K) |
| $k_f$ | `fluid_k` | Thermal conductivity | kW/(m K) |
| $\mu$ | `fluid_visc` | Dynamic viscosity | Pa s |
| $Re$ | — | Reynolds number | — |
| $Pr$ | — | Prandtl number | — |
| $h_{in}$ | `hinside` | Internal convective heat transfer coefficient | kJ/(m² s K) |
| $h_{amb}$ | `hamb` | Ambient (external) heat transfer coefficient | kJ/(m² s K) |
| $T_{amb}$ | `Tamb` | Ambient temperature | °C |
| $R$ | `R` | Pipe inner radius | m |
| $D$ | — | Pipe inner diameter, $D = 2R$ | m |
| $L$ | `L` | Collector pipe length | m |
| $dz$ | `dz` | Segment length | m |
| $N$ | `N` | Number of spatial segments | — |
| $A_c$ | — | Pipe cross-sectional area, $A_c = \pi R^2$ | m² |
| $W$ | `MirrorWidth` | Collector mirror aperture width | m |
| $I$ | `Irad1` | Direct normal irradiance (DNI) | kW/m² |
| $\epsilon$ | `eff` / `eff1` | Optical efficiency | — |
| $D_{proc}$ | `ProcessD` | Absorbed solar flux per unit pipe length | kW/m² |
| $D_{disp}$ | `Dispersion` | Axial dispersion coefficient | kJ/(m s K) |
| $T_{in}$ | `initial_Tin` | Pipe inlet fluid temperature | °C |
| $T_b[k]$ | `Tb[k]` | Fluid temperature at segment $k$, before timestep | °C |
| $T_a[k]$ | `Ta[k]` | Fluid temperature at segment $k$, after timestep | °C |
| $T_{pipe}[k]$ | `PipeT[k]` | Pipe wall temperature at segment $k$ | °C |
| $\tau_{pipe}$ | — | Pipe wall thermal time constant (= 10 s) | s |
| $\dot{m}$ | `Mdot_line` | Mass flow rate, single line | kg/s |
| $F$ | `F_line` | Volumetric flow rate, single line | m³/s |
| $F_{total}$ | `Ftotal` | Total volumetric flow rate (all lines) | m³/s |
| $s$ | `spumps` | Pump speed fraction | — |
| $s_{targ}$ | `spumpstarg` | Pump speed target | — |
| $n_{ref}$ | `sref` | Reference pump speed (= 2970 rpm) | rpm |
| $F_{max,ref}$ | `Fmaxref` | Reference maximum flow rate | m³/s |
| $h_{max,ref}$ | `hmaxref` | Reference pump head | kPa |
| $\tau_p$ | `pumptau` | Pump lag time constant | s |
| $x_v$ | `valvex` | Valve stem position | — |
| $x_{v,targ}$ | `valvextarg` | Valve stem target | — |
| $\tau_v$ | `valvetau` | Valve lag time constant | s |
| $R_v$ | `valveR` | Valve rangeability (= 50) | — |
| $C_v$ | `Cv` | Valve sizing coefficient | m³/(s √kPa) |
| $G$ | `G` | Valve seat pressure-drop coefficient | kPa/(m³/s)² |
| $f_a$ | `flowaest` | Line pressure-drop coefficient (estimated) | kPa s²/m⁶ |
| $F_b$ | `Flowb` | Boiler/header pressure-drop coefficient | kPa s²/m⁶ |
| $\Delta P_{pump}$ | `dPpump` | Pump pressure rise | kPa |
| $\Delta t$ | `dt` | Simulation timestep | s |

---

## 1. Fluid Properties

All fluid properties are polynomial fits evaluated at the local temperature
$T$ (°C), first converted to Kelvin:

$$T_K = T + 273.15$$

**Density**

$$\rho(T) = 960.73 + 0.11489\, T_K - 0.001082\, T_K^2 \quad [\text{kg/m}^3]$$

**Specific heat capacity**

$$C_p(T) = \frac{1108.027 + 1.70714\, T_K}{1000} \quad [\text{kJ/(kg K)}]$$

**Thermal conductivity**

$$k_f(T) = \frac{0.19091 - 0.0001894\, T_K}{1000} \quad [\text{kW/(m K)}]$$

**Dynamic viscosity**

$$\mu(T) = 0.0000394059 \exp\!\left(\frac{1636.999}{T_K}\right) - 0.0002115 \quad [\text{Pa s}]$$

Temperature is clamped to $[250,\,500]$ °C before evaluating these
expressions.

---

## 2. Internal Heat Transfer Coefficient

The Dittus–Boelter correlation for turbulent pipe flow:

$$Re = \frac{4 F \rho}{\pi D \mu}, \qquad Pr = \frac{C_p \mu}{k_f}$$

$$h_{in}(T, F) = \frac{k_f}{D}\, 0.023\, Re^{0.8}\, Pr^{0.4} \quad [\text{kJ/(m}^2\text{ s K)}]$$

---

## 3. Valve Characteristic

An equal-percentage valve with rangeability $R_v = 50$:

$$f(x_v) = R_v^{\,x_v - 1}$$

---

## 4. Volumetric Flow Rate from Valve Position

$$F_i = C_v\, f(x_{v,i})\, \sqrt{\frac{\Delta P_{pump}}{G + \bigl(f_{a,i} + 9 F_b\bigr)\bigl(C_v f(x_{v,i})\bigr)^2}}$$

The term $9 F_b$ is the linearised boiler-and-header pressure drop (exact at
balanced equal-flow operation).

---

## 5. Pump Head and Pressure Drop

The pump is modelled by affinity laws referenced to a rated operating point:

$$n_{pump} = s \cdot n_{ref}, \qquad F_{max} = F_{max,ref}\,\frac{n_{pump}}{n_{ref}}, \qquad h_{max} = h_{max,ref}\left(\frac{n_{pump}}{n_{ref}}\right)^2$$

$$\Delta P_{pump} = h_{max}\left[1 - \left(\frac{\min(F_{total}, F_{max})}{F_{max}}\right)^{4.347}\right]$$

with $n_{ref} = 2970$ rpm, $F_{max,ref} = 224.629/3600$ m³/s,
$h_{max,ref} = 128\,\rho\,g / 1000$ kPa.

---

## 6. Hydraulic Balance (rootfinder)

The pump pressure $\Delta P_{pump}$ depends on $F_{total}$, and each line
flow $F_i$ depends on $\Delta P_{pump}$ — a circular dependency.  The
`CasadiSolarCollectorModel` resolves this with an embedded CasADi Newton
rootfinder (replacing the 10-step successive-substitution loop in the
original VBA).  At each timestep the rootfinder finds $F_{total}^*$ such
that:

$$\sum_{i=1}^{3} F_i\!\left(x_{v,i},\; \Delta P_{pump}(F_{total}^*,\, s)\right) = F_{total}^*$$

Once $F_{total}^*$ is known, $\Delta P_{pump}$ and all $F_i$ follow
explicitly.

---

## 7. Pump Speed Dynamics

First-order lag from target to actual pump speed:

$$s^{k+1} = \left(1 - e^{-\Delta t / \tau_p}\right) s_{targ} + e^{-\Delta t / \tau_p}\, s^k$$

---

## 8. Valve Position Dynamics

First-order lag with hard limits:

$$x_v^{k+1} = \operatorname{clip}\!\left[\left(1 - e^{-\Delta t / \tau_v}\right) x_{v,targ} + e^{-\Delta t / \tau_v}\, x_v^k,\; 0.1,\; 1.0\right]$$

---

## 9. Pipe Wall Temperature

The pipe wall temperature is updated by a first-order lag towards the
steady-state equilibrium $T_{pipe,eq}$:

$$T_{pipe,eq}[k] = \frac{D_{proc} + h_{in}\, T_b[k] + h_{amb}\, T_{amb}}{h_{in} + h_{amb}}$$

where $D_{proc} = I\, W\, \epsilon / (\pi R)$ is the absorbed solar flux
divided by the pipe perimeter.

$$T_{pipe}^{k+1}[k] = \left(1 - e^{-\Delta t / \tau_{pipe}}\right) T_{pipe,eq}[k] + e^{-\Delta t / \tau_{pipe}}\, T_{pipe}^k[k]$$

with $\tau_{pipe} = 10$ s.

---

## 10. Fluid Temperature — Finite-Volume PDE

The fluid temperature along each collector line is advanced using an
explicit Euler step on a 1-D finite-volume grid of $N$ equal segments of
length $dz$.

**Entrance node** ($k = 1$, upstream boundary condition $T_{in}$):

$$T_a[1] = T_b[1] + \Delta t \left[
  \frac{h_{in}}{R\,\rho C_p}\bigl(T_{pipe}[1] - T_b[1]\bigr)
  - \frac{\dot{m}}{\rho A_c\, dz}\bigl(T_b[1] - T_{in}\bigr)
  + \frac{D_{disp}}{\rho C_p\, dz^2}\bigl(T_b[2] - 2T_b[1] + T_{in}\bigr)
\right]$$

**Interior nodes** ($2 \le k \le N-1$, backward-difference advection):

$$T_a[k] = T_b[k] + \Delta t \left[
  \frac{h_{in}}{R\,\rho C_p}\bigl(T_{pipe}[k] - T_b[k]\bigr)
  - \frac{\dot{m}}{\rho A_c\, dz}\bigl(T_b[k] - T_b[k-1]\bigr)
  + \frac{D_{disp}}{\rho C_p\, dz}\bigl(T_b[k+1] - 2T_b[k] + T_b[k-1]\bigr)
\right]$$

**Exit node** ($k = N$, zero-gradient boundary):

$$T_a[N] = T_b[N] + \Delta t \left[
  \frac{h_{in}}{R\,\rho C_p}\bigl(T_{pipe}[N] - T_b[N]\bigr)
  - \frac{\dot{m}}{\rho A_c\, dz}\bigl(T_b[N] - T_b[N-1]\bigr)
  + \frac{D_{disp}}{\rho C_p\, dz}\bigl(-T_b[N] + T_b[N-1]\bigr)
\right]$$

All fluid properties ($\rho$, $C_p$, $h_{in}$) are evaluated at the local
segment temperature $T_b[k]$.  At the end of the timestep: $T_b \leftarrow T_a$.

> **Note on the dispersion coefficient:** The entrance-node dispersion term
> uses $dz^2$ in the denominator (second-order finite difference); interior
> and exit nodes use $dz$ (as in Rhinehart's original derivation, textbook
> p. 122).

---

## 11. State-Space Summary

The model has the structure $x^{k+1} = F(t,\, x^k,\, u^k)$,
$y^k = H(t,\, x^k,\, u^k)$, with:

**State** $x \in \mathbb{R}^n$, $n = 1 + 3 n_\ell + 2 n_\ell N$
($n_\ell = 3$ lines):

$$x = \bigl[s,\; x_{v,1..3},\; F_{1..3},\; \dot{m}_{1..3},\; T_{b,1..3,1..N},\; T_{pipe,1..3,1..N}\bigr]^\top$$

**Input** $u \in \mathbb{R}^{n_u}$, $n_u = 1 + n_\ell$:

$$u = \bigl[s_{targ},\; x_{v,targ,1..3}\bigr]^\top$$

**Output** $y \in \mathbb{R}^{n_y}$, $n_y = 1 + 2 n_\ell$:

$$y = \bigl[F_{total},\; F_{1..3},\; T_{a,1..3,N}\bigr]^\top$$

---

## 12. Simulation Step Sequence

This section describes the main computation sequence executed by
`SolarCollectorSimulator.step(dt)` in `src/solar_collector/simulation.py`.

### Overview

A single simulation step is a sequential update of the system state:

1. Advance simulation time
2. Update process variables (pump, flow, temperatures)
3. Measure noisy outputs
4. Apply control logic
5. Compute evaluation metrics
6. Record history for later analysis

### `step(dt)`

- `self.state.simtime += dt`
- `self._process_step(dt)`
- `self._measure_step(dt)`
- `self._control_step(dt)`
- `self._evaluate_step()`
- `self._record_history()`

### `_process_step(dt)`

This is the core process update.

**Pump and valve dynamics**

- `state.spumps = pump_speed_update(state.spumpstarg, state.spumps, dt, config.pumptau)`
- `state.valvex = valve_state_update(state.valvextarg, state.valvex, dt, config.valvetau)`

**Pump head and pressure** (after solving hydraulic balance)

- `Fmax, dPpump = pump_head_and_dP(F_total, state.spumps, config.dens)`

**Flow rate per line**

- `state.F[line] = flow_rate_from_valve(...)`
- `state.Mdot[line] = config.dens * state.F[line]`

**Thermal update per line** (`thermal_line_step`)

- Inputs: `Tb[line]`, `config.initial_Tin`, `state.Mdot[line]`, `config.R`,
  `config.dz`, `dt`, `state.Irad1`, `config.MirrorWidth`, `state.eff1[line]`,
  `config.hamb`, `config.Tamb`, `state.PipeT[line]`, `config.Dispersion`
- Outputs: `Ta_line`, `PipeT_line`
- State updates: `state.Ta[line]`, `state.PipeT[line]`, `state.Tb[line]`

**Aggregate flow state**

- `state.Ftotal = np.sum(state.F)`
- `state.Mdottotal = np.sum(state.Mdot)`

### `_measure_step(dt)`

- `measured_noise = self.rng.normal(scale=self.config.noise_std, size=3)`
- `state.Fmeas = 0.95 * state.F * (1.0 + measured_noise)`
- `state.T2meas = [exit temperature for each line]`
- `state.T1meas = [exit temperature for each line]`
- `state.Fmeasfilt = 0.9 * state.Fmeas + 0.1 * state.Fmeasfilt`

### `_control_step(dt)`

Placeholder for control logic (setpoint adjustment, flow control, pump speed
control using measurements and model state).

### `_evaluate_step()`

Placeholder for performance metrics, errors, or derived diagnostics.

### `_record_history()`

Appends to simulation history: `simtime`, average `T1` and `T2`, `F_total`,
`pump_speed`.
