"""Live simulation of the solar collector with real-time animation.

Opens a matplotlib window showing:
  - Fluid and pipe-wall temperature profiles along the collector
  - Scrolling time series: exit temperatures, mass flow rates,
    pump speed (target & actual), solar irradiance, valve positions
  - Sliders to adjust pump speed, valve positions, irradiance, Tamb, and Tin

Usage:
    python run_simulation_live.py
"""

import numpy as np

from solar_collector.casadi_model import CasadiSolarCollectorModel
from solar_collector.live_sim import (
    SolarCollectorLiveSim,
    _PUMP_MIN,
    _VALVE_MIN,
)
from solar_collector.model import make_initial_state
from solar_collector.simulation import SimulationConfig

# ── Simulation parameters ──────────────────────────────────────────────────

# Initial conditions: ambient cold-start (actuators at minimum, no irradiance)
SPUMP_INIT = _PUMP_MIN  # minimum pump speed
VALVE_INIT = _VALVE_MIN  # minimum valve position
IRAD_INIT = 0.0  # no irradiance (pre-sunrise)
STEPS_PER_FRAME = 1  # simulation steps per animation frame
HISTORY_LEN = 600  # time points kept in scrolling plots (~148 s at dt=0.246)
FRAME_INTERVAL_MS = 50  # target ms between frames (≈ 20 fps ceiling)
PLOT_HORIZON = 60.0  # seconds of history shown in time-series plots

# ── Plant configuration ────────────────────────────────────────────────────

cfg = SimulationConfig(
    N=100,
    dz=1.92,
    R=0.035,
    L=192.0,
    MirrorWidth=5.76,
    dens=671.14,
    Cp=2.2,
    Tamb=10.0,
    hamb=0.0036,
    Dispersion=0.0,
    eff=0.6,
    initial_Tin=300.0,
    initial_T1SP=395.0,
    initial_spump=SPUMP_INIT,
    dt=0.246300656,
    use_backward_diff=True,
    Irad=IRAD_INIT,
    Irad1=IRAD_INIT,
)

# ── Build plant model ──────────────────────────────────────────────────────

print("Building plant model ...", flush=True)
plant = CasadiSolarCollectorModel(cfg, name="plant")
print(
    f"  n = {plant.n}  (N={cfg.N} segments × {plant.n_lines} lines)  "
    f"nu = {plant.nu}  ny = {plant.ny}"
)

# ── Initial state and inputs: ambient cold-start ───────────────────────────
# All temperatures set to Tamb; pump off, valves at minimum, no irradiance.

x0 = make_initial_state(
    plant, T_init=cfg.Tamb, spump=SPUMP_INIT, valvex=VALVE_INIT
)

u0 = np.array(
    [
        SPUMP_INIT,
        VALVE_INIT,
        VALVE_INIT,
        VALVE_INIT,
        IRAD_INIT,
        cfg.Tamb,
        cfg.Tamb,
    ]
)

# ── Run live simulation ────────────────────────────────────────────────────

live = SolarCollectorLiveSim(
    plant,
    x0,
    u0,
    steps_per_frame=STEPS_PER_FRAME,
    history_len=HISTORY_LEN,
    frame_interval_ms=FRAME_INTERVAL_MS,
    plot_horizon=PLOT_HORIZON,
)
live.run()
