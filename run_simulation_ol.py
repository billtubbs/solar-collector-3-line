"""Open-loop simulation of the solar collector.

Uses make_open_loop_simulation to build a single fixed-horizon CasADi
simulation function, then calls it repeatedly in chunks of N_CHUNK steps.

N_STEPS and T_STEP_K must both be multiples of N_CHUNK so that the pump
speed step change always falls on a chunk boundary — no mid-chunk splitting
is needed and only one simulation function is required.

Results are saved to results/simulation_ol.npz.

Usage:
    python run_simulation_ol.py
"""

import time
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from plot_utils import make_tsplots
from solar_collector.casadi_model import CasadiSolarCollectorModel
from solar_collector.simulation import (
    SimulationConfig,
    make_open_loop_simulation,
)


# ── Simulation parameters ──────────────────────────────────────────────────

N_STEPS = 3_000  # total number of simulation steps (multiple of N_CHUNK)
T_STEP_K = 1_500  # pump speed step-up at this step (multiple of N_CHUNK)
SPUMP_NOMINAL = 0.45  # pump speed before step
SPUMP_STEPPED = 0.70  # pump speed after step
IRAD_NOMINAL = 0.95  # [kW/m²] direct normal irradiance (fixed)
N_CHUNK = 100  # steps per CasADi simulation function call

assert N_STEPS % N_CHUNK == 0, "N_STEPS must be a multiple of N_CHUNK"
assert T_STEP_K % N_CHUNK == 0, "T_STEP_K must be a multiple of N_CHUNK"


# ── Plant configuration (spreadsheet base case) ────────────────────────────

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
    initial_spump=SPUMP_NOMINAL,
    dt=0.246300656,
    use_backward_diff=True,
    Irad=IRAD_NOMINAL,
    Irad1=IRAD_NOMINAL,
)


# ── Build plant model ──────────────────────────────────────────────────────

print("Building plant model ...", flush=True)
t0 = time.perf_counter()
plant = CasadiSolarCollectorModel(cfg, name="plant")
print(f"  Done in {time.perf_counter() - t0:.1f} s")
print(
    f"  State dimension n = {plant.n}  "
    f"(N={cfg.N} segments × {plant.n_lines} lines)"
)


# ── Build simulation function ──────────────────────────────────────────────

print(f"\nBuilding simulation function (N_CHUNK={N_CHUNK}) ...", flush=True)
t0 = time.perf_counter()
sim = make_open_loop_simulation(plant, N_CHUNK, name="sim")
print(f"  Done in {time.perf_counter() - t0:.1f} s")
print(f"  {sim}")


# ── Initial state ──────────────────────────────────────────────────────────
# Tb(line, k)    = 300 + 95*k/N  °C  (linear ramp from VBA Initialize)
# PipeT(line, k) = 354 + 95*k/N  °C  (~54 °C above fluid)
# F per line: solved from the hydraulic balance so there is no transient
# jump at t=0 (the rootfinder is the same one used inside each model step).

N = cfg.N
n_lines = plant.n_lines
n = plant.n

# Hydraulic-balance Mdot for the initial pump/valve conditions
p_init = np.array([SPUMP_NOMINAL, 0.9, 0.9, 0.9])
Ftotal_ss = float(plant.flow_balance(3 * 0.003, p_init)[0])
mdot_init = cfg.dens * Ftotal_ss / n_lines

x0 = np.zeros(n)
x0[0] = SPUMP_NOMINAL
x0[1:4] = 0.9
x0[4:7] = mdot_init

# Column-major layout: flat index k*n_lines + line  →  Tb[line, k]
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


# ── Simulation loop ────────────────────────────────────────────────────────

dt = cfg.dt
t_array = np.arange(N_STEPS + 1) * dt
u_pre = np.array([SPUMP_NOMINAL, 0.9, 0.9, 0.9])
u_post = np.array([SPUMP_STEPPED, 0.9, 0.9, 0.9])

n_chunks = N_STEPS // N_CHUNK
Y = np.empty((N_STEPS + 1, plant.ny))
X_ds = np.empty((n_chunks + 1, n))
t_ds = np.empty(n_chunks + 1)

t_step_s = T_STEP_K * dt
print(
    f"\nRunning {N_STEPS:,} steps  (dt = {dt:.4f} s  →  {N_STEPS * dt:.1f} s total)"
)
print(
    f"  Pump speed step-up: {SPUMP_NOMINAL} → {SPUMP_STEPPED}  "
    f"at step {T_STEP_K} (t = {t_step_s:.1f} s)"
)

Y[0] = np.asarray(plant.H(0.0, x0, u_pre)).ravel()
X_ds[0] = x0
t_ds[0] = 0.0

x = x0.copy()
t_start = time.perf_counter()

for i in range(n_chunks):
    k = i * N_CHUNK
    u_row = u_pre if k < T_STEP_K else u_post
    t_c = t_array[k : k + N_CHUNK + 1]
    U_c = np.tile(u_row, (N_CHUNK, 1))
    X_c, Y_c = sim(t_c, U_c, x)
    x = np.asarray(X_c)[-1]
    Y[k + 1 : k + N_CHUNK + 1] = np.asarray(Y_c)[1:]
    X_ds[i + 1] = x
    t_ds[i + 1] = t_array[k + N_CHUNK]

elapsed = time.perf_counter() - t_start
print(f"\nDone in {elapsed:.2f} s  ({elapsed / N_STEPS * 1e3:.3f} ms/step)")


# ── Save results ───────────────────────────────────────────────────────────

results_dir = Path("results")
results_dir.mkdir(exist_ok=True)
out_path = results_dir / "simulation_ol.npz"

np.savez_compressed(
    out_path,
    t=t_array,
    Y=Y,
    X_ds=X_ds,
    t_ds=t_ds,
    output_names=np.array(plant.output_names),
    spump_step_t=np.array([t_step_s]),
    spump_nominal=np.array([SPUMP_NOMINAL]),
    spump_stepped=np.array([SPUMP_STEPPED]),
    irad=np.array([IRAD_NOMINAL]),
)

print(f"Saved to {out_path}")
print(f"  Y shape   : {Y.shape}  — {plant.output_names}")
print(
    f"  X_ds shape: {X_ds.shape}  "
    f"(every {N_CHUNK} steps = {N_CHUNK * dt:.1f} s)"
)
print("\nFinal state summary:")
mdot_final = [float(Y[-1, i]) for i in range(n_lines)]
print(f"  Mdottotal: {sum(mdot_final):.5f}  kg/s")
for i in range(n_lines):
    print(f"  Mdot{i + 1}   : {mdot_final[i]:.5f}  kg/s")
for i in range(n_lines):
    T2exit_idx = n_lines + (N - 1) * n_lines + i
    print(f"  T2exit{i + 1} : {float(Y[-1, T2exit_idx]):.2f}  °C")


# ── Build results DataFrame ────────────────────────────────────────────────
# Rows: one per state snapshot (every N_CHUNK steps), indexed by time [s].
# X_ds[i] and Y[i*N_CHUNK] both correspond to the state at step i*N_CHUNK.

input_names = ["spumpstarg", "valvextarg1", "valvextarg2", "valvextarg3"]

cols = pd.MultiIndex.from_tuples(
    [("inputs", name) for name in input_names]
    + [("states", name) for name in plant.state_names]
    + [("outputs", name) for name in plant.output_names]
)

snap_steps = np.arange(n_chunks + 1) * N_CHUNK
u_snaps = np.where(
    snap_steps[:, None] < T_STEP_K,
    u_pre[None, :],
    u_post[None, :],
)

all_data = np.hstack(
    [
        u_snaps,  # inputs  ((n_chunks+1) × 4)
        X_ds,  # states  ((n_chunks+1) × n)
        Y[snap_steps],  # outputs ((n_chunks+1) × ny)
    ]
)

sim_results = pd.DataFrame(all_data, index=t_ds, columns=cols)
sim_results.index.name = "time_s"

csv_path = results_dir / "simulation_ol.csv"
sim_results.to_csv(csv_path)
print(f"\nSaved DataFrame to {csv_path}")
print(
    f"  Shape : {sim_results.shape}  "
    f"({sim_results.shape[0]} snapshots × {sim_results.shape[1]} columns)"
)
print(
    f"  Level-0 groups : {sim_results.columns.get_level_values(0).unique().tolist()}"
)

# ── Make time series plots ───────────────────────────────────────────────

exit_temp_labels = [f"Tb{i + 1}_{N}" for i in range(n_lines)]
mdot_labels = [f"Mdot{i + 1}" for i in range(n_lines)]
valve_labels = ["valvextarg1", "valvextarg2", "valvextarg3"]

plot_data = {
    "Exit Temperatures": {
        "y": sim_results["outputs"][exit_temp_labels].values,
        "labels": exit_temp_labels,
    },
    "Mass Flow Rates": {
        "y": sim_results["outputs"][mdot_labels].values,
        "labels": mdot_labels,
    },
    "Valve Positions": {
        "y": sim_results["inputs"][valve_labels].values,
        "labels": valve_labels,
        "kind": "step",
    },
    "Pump Speed": {
        "y": sim_results["inputs"][["spumpstarg"]].values,
        "labels": ["spumpstarg"],
        "kind": "step",
    },
}
fig, axes = make_tsplots(
    sim_results.index,
    plot_data,
    t_label="Time (seconds)",
)
plt.tight_layout()
plt.show()
