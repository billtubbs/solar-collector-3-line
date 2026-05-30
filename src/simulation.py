import numpy as np
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .model import (
    flow_rate_from_valve,
    pump_head_and_dP,
    pump_speed_update,
    thermal_line_step,
    valve_state_update,
)


@dataclass
class SimulationConfig:
    N: int = 20
    dz: float = 0.1
    R: float = 0.035
    L: float = 20.0
    MirrorWidth: float = 2.5
    dens: float = 671.14
    Cp: float = 1.8
    Tamb: float = 300.0
    hamb: float = 0.036
    Dispersion: float = 0.01
    valvetau: float = 2.0
    pumptau: float = 2.0
    Cv: float = 10.0 / 3600.0
    Flowa: float = 5_000_000.0
    Flowb: float = 0.5 * (4.0 / 9.0) * 5_000_000.0
    G: float = field(init=False)
    initial_Tin: float = 280.0
    initial_T1SP: float = 360.0
    initial_spump: float = 0.8
    noise_std: float = 0.05
    use_backward_diff: bool = True
    dt: float = 0.1

    def __post_init__(self):
        self.G = self.dens / 1000.0


@dataclass
class SimulationState:
    simtime: float = 0.0
    spumps: float = 0.0
    spumpstarg: float = 0.0
    valvex: np.ndarray = field(default_factory=lambda: np.full(3, 0.9))
    valvextarg: np.ndarray = field(default_factory=lambda: np.full(3, 0.9))
    F: np.ndarray = field(default_factory=lambda: np.zeros(3))
    Mdot: np.ndarray = field(default_factory=lambda: np.zeros(3))
    Tb: np.ndarray = field(default_factory=lambda: np.zeros((3, 20)))
    Ta: np.ndarray = field(default_factory=lambda: np.zeros((3, 20)))
    PipeT: np.ndarray = field(default_factory=lambda: np.zeros((3, 20)))
    eff1: np.ndarray = field(default_factory=lambda: np.ones(3) * 0.8)
    epsilonest: np.ndarray = field(default_factory=lambda: np.ones(3) * 0.8)
    valvexm: np.ndarray = field(default_factory=lambda: np.ones(3) * 0.9)
    Fmeas: np.ndarray = field(default_factory=lambda: np.zeros(3))
    Fmeasfilt: np.ndarray = field(default_factory=lambda: np.zeros(3))
    T1meas: np.ndarray = field(default_factory=lambda: np.zeros(3))
    T2meas: np.ndarray = field(default_factory=lambda: np.zeros(3))
    T2SP: np.ndarray = field(default_factory=lambda: np.zeros(3))
    T2model: np.ndarray = field(default_factory=lambda: np.zeros(3))
    Iterm: np.ndarray = field(default_factory=lambda: np.zeros(3))
    flowaest: np.ndarray = field(default_factory=lambda: np.zeros(3))
    effdrop: np.ndarray = field(default_factory=lambda: np.zeros(3))
    Ftotal: float = 0.0
    Mdottotal: float = 0.0
    Irad: float = 0.95
    Irad1: float = 0.95
    eff: float = 0.8
    noise_seed: Optional[int] = None
    history: Dict[str, List[float]] = field(
        default_factory=lambda: {
            "simtime": [],
            "T1": [],
            "T2": [],
            "F_total": [],
            "pump_speed": [],
        }
    )


class SolarCollectorSimulator:
    def __init__(
        self,
        config: SimulationConfig,
        rng: Optional[np.random.Generator] = None,
    ):
        self.config = config
        self.state = SimulationState(
            spumps=config.initial_spump,
            spumpstarg=config.initial_spump,
            valvex=np.full(3, 0.9),
            valvextarg=np.full(3, 0.9),
            F=np.full(3, 0.01),
            Mdot=np.full(3, 0.01 * config.dens),
            Tb=np.tile(
                np.linspace(
                    config.initial_Tin, config.initial_Tin + 95.0, config.N
                ),
                (3, 1),
            ),
            Ta=np.tile(
                np.linspace(
                    config.initial_Tin, config.initial_Tin + 95.0, config.N
                ),
                (3, 1),
            ),
            PipeT=np.tile(
                np.linspace(
                    config.initial_Tin + 40.0,
                    config.initial_Tin + 135.0,
                    config.N,
                ),
                (3, 1),
            ),
            eff1=np.full(3, config.eff),
            epsilonest=np.full(3, config.eff),
            valvexm=np.full(3, 0.9),
            T2SP=np.full(
                3,
                config.initial_Tin
                + (config.initial_T1SP - config.initial_Tin) / 2.0,
            ),
            T2model=np.full(
                3,
                config.initial_Tin
                + (config.initial_T1SP - config.initial_Tin) / 2.0,
            ),
            Fmeasfilt=np.full(3, 0.01),
            noise_seed=config.initial_spump,
        )
        self.rng = rng or np.random.default_rng(self.state.noise_seed)
        self._initialize_state()

    def _initialize_state(self):
        self.state.F = self.state.Mdot / self.config.dens
        self.state.Mdottotal = np.sum(self.state.Mdot)
        self.state.Ftotal = np.sum(self.state.F)

    def step(self, dt: Optional[float] = None):
        dt = dt if dt is not None else self.config.dt
        self.state.simtime += dt
        self._process_step(dt)
        self._measure_step(dt)
        self._control_step(dt)
        self._evaluate_step()
        self._record_history()

    def _process_step(self, dt: float):
        config = self.config
        state = self.state

        state.spumps = pump_speed_update(
            state.spumpstarg, state.spumps, dt, config.pumptau
        )
        state.valvex = valve_state_update(
            state.valvextarg, state.valvex, dt, config.valvetau
        )

        F_total = state.Ftotal
        Fmax, dPpump = pump_head_and_dP(F_total, state.spumps, config.dens)

        for line in range(3):
            state.F[line] = flow_rate_from_valve(
                state.valvex[line],
                config.Cv,
                dPpump,
                config.G,
                state.flowaest[line],
                config.Flowb,
            )
            state.Mdot[line] = config.dens * state.F[line]

        state.Ftotal = float(np.sum(state.F))
        state.Mdottotal = float(np.sum(state.Mdot))

        for line in range(3):
            Ta_line, PipeT_line = thermal_line_step(
                state.Tb[line],
                config.initial_Tin,
                state.Mdot[line],
                config.R,
                config.dz,
                dt,
                state.Irad1,
                config.MirrorWidth,
                state.eff1[line],
                config.hamb,
                config.Tamb,
                state.PipeT[line],
                config.Dispersion,
                method="B" if config.use_backward_diff else "F",
            )
            state.Ta[line] = Ta_line
            state.PipeT[line] = PipeT_line
            state.Tb[line] = Ta_line

    def _measure_step(self, dt: float):
        state = self.state
        measured_noise = self.rng.normal(scale=self.config.noise_std, size=3)
        state.Fmeas = 0.95 * state.F * (1.0 + measured_noise)
        state.T2meas = np.array([state.Ta[line, -1] for line in range(3)])
        state.T1meas = np.array([state.Ta[line, -1] for line in range(3)])
        state.Fmeasfilt = 0.9 * state.Fmeas + 0.1 * state.Fmeasfilt

    def _control_step(self, dt: float):
        # Placeholder for control logic: T1, T2, flow, and pump control.
        pass

    def _evaluate_step(self):
        # Placeholder for evaluation metrics and output state.
        pass

    def _record_history(self):
        state = self.state
        self.state.history["simtime"].append(state.simtime)
        self.state.history["T1"].append(float(np.mean(state.Ta[:, -1])))
        self.state.history["T2"].append(float(np.mean(state.Ta[:, -1])))
        self.state.history["F_total"].append(float(state.Ftotal))
        self.state.history["pump_speed"].append(float(state.spumps))

    def set_spump_target(self, value: float):
        self.state.spumpstarg = np.clip(value, 0.0, 1.0)
