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
from solar_collector.live_sim import SolarCollectorLiveSim
from solar_collector.simulation import SimulationConfig

# ── Simulation parameters ──────────────────────────────────────────────────

SPUMP_INIT = 0.45  # initial pump speed
IRAD_INIT = 0.95  # [kW/m²] initial solar irradiance
STEPS_PER_FRAME = 1  # simulation steps per animation frame
HISTORY_LEN = 600  # time points kept in scrolling plots (~148 s at dt=0.246)
FRAME_INTERVAL_MS = 50  # target ms between frames (≈ 20 fps ceiling)

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

# ── Initial state ──────────────────────────────────────────────────────────
# Tb: linear ramp 300 → 395 °C along each line (VBA Initialize)
# PipeT: linear ramp 354 → 449 °C (~54 °C above fluid)
# Mdot: consistent with hydraulic balance at initial pump/valve conditions

N = cfg.N
n_lines = plant.n_lines
n = plant.n

# Hydraulic-balance Mdot for initial conditions
p_init = np.array([SPUMP_INIT, 0.9, 0.9, 0.9])
Ftotal_ss = float(plant.flow_balance(3 * 0.003, p_init)[0])
mdot_init = cfg.dens * Ftotal_ss / n_lines

x0 = np.zeros(n)
x0[0] = SPUMP_INIT
x0[1:4] = 0.9
x0[4:7] = mdot_init

tb_off = 1 + 2 * n_lines
pipe_off = tb_off + n_lines * N
Tb_profile = 300.0 + 95.0 * np.arange(1, N + 1) / N
PipeT_profile = 354.0 + 95.0 * np.arange(1, N + 1) / N
x0[tb_off : tb_off + n_lines * N] = np.tile(Tb_profile, (n_lines, 1)).flatten(
    order="F"
)
x0[pipe_off : pipe_off + n_lines * N] = np.tile(
    PipeT_profile, (n_lines, 1)
).flatten(order="F")

# ── Initial input vector ───────────────────────────────────────────────────

u0 = np.array(
    [SPUMP_INIT, 0.9, 0.9, 0.9, IRAD_INIT, cfg.Tamb, cfg.initial_Tin]
)

# ── Run live simulation ────────────────────────────────────────────────────

live = SolarCollectorLiveSim(
    plant,
    x0,
    u0,
    steps_per_frame=STEPS_PER_FRAME,
    history_len=HISTORY_LEN,
    frame_interval_ms=FRAME_INTERVAL_MS,
)
live.run()
