# Solar Collector — 3 Line Dynamic Simulator

Python/CasADi reimplementation of Russ Rhinehart's parabolic solar collector
plant simulator.

## Purpose

This project models a parabolic trough solar collector with three parallel
collection lines and a shared pump.  Pressurised thermal oil flows through
the lines, gaining heat from concentrated solar radiation, and exits to a
boiler.  The model captures:

- **Fluid thermodynamics** — temperature-dependent density, viscosity, heat
  capacity, and conductivity of the working fluid
- **Pipe heat transfer** — internal convection (Dittus–Boelter), ambient
  losses, and a dynamic pipe-wall temperature
- **Hydraulic network** — pump affinity-law pressure curve, equal-percentage
  control valves, and a Newton rootfinder for the coupled pump/flow balance
- **Actuator dynamics** — first-order lag for pump speed and valve positions

## Objectives

1. Provide a fast, numerically accurate benchmark plant model suitable for 
   control design and evaluation experiments.
2. Expose the model as a CasADi discrete-time state-space object
   (`CasadiSolarCollectorModel`) so it can be used directly in gradient-based
   optimisation, MPC, and RL training loops.
3. Wrap the simulator as a [Gymnasium](https://gymnasium.farama.org/)
   environment for RL-based control research.

## Documentation

- **Model equations, nomenclature, and simulation step sequence:**
  [`docs/solar_collector_model.md`](docs/solar_collector_model.md)

## Repository layout

```
run_simulation_ol.py          # open-loop simulation script (pump step, saves results/)
run_simulation_live.py        # real-time interactive animated simulation

src/
    plot_utils.py             # lightweight Matplotlib helpers (make_tsplots, make_ioplots)
    solar_collector/
        model.py              # pure-Python physics primitives (NumPy + CasADi compatible)
        casadi_model.py       # CasadiSolarCollectorModel — discrete-time state-space model
        casadi_ctrls.py       # four CasADi discrete-time cascade controllers
        simulation.py         # SimulationConfig, simulate(), make_open_loop_simulation()
        live_sim.py           # SolarCollectorLiveSim — real-time animated interactive UI

excel/macros/                 # VBA macros extracted from the original Excel workbook
results/                      # simulation output files (.npz / .csv)
tests/                        # pytest regression tests
docs/                         # model equations, nomenclature, and Excel workbook reference
tools/                        # utility scripts (e.g. extract_vba.py)
```

## Quick setup

Prerequisites: Python 3.9 or newer

```bash
pip install -U pip
# install runtime dependencies only
pip install .
# or install runtime + developer extras (tests, ruff)
pip install -e ".[dev]"
```

## Run tests

```bash
pytest
```

## License and attribution

License: MIT  
Original VBA model: Russ Rhinehart  
Python/CasADi reimplementation: Research Team
