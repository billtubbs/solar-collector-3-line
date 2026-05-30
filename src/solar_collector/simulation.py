import copy
import numpy as np
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .model import (
    flow_rate_from_valve,
    hinside,
    pump_head_and_dP,
    pump_speed_update,
    rho,
    thermal_line_step,
    valve_state_update,
)


def process_step(
    state: "SimulationState",
    config: "SimulationConfig",
    dt: float,
) -> "SimulationState":
    new_state = copy.deepcopy(state)
    exp = config.exp
    sqrt = config.sqrt
    rho_func = config.rho_func
    hinside_func = config.hinside_func
    pi = config.pi

    new_state.spumps = pump_speed_update(
        new_state.spumpstarg,
        new_state.spumps,
        dt,
        config.pumptau,
        exp=exp,
    )
    new_state.valvex = valve_state_update(
        new_state.valvextarg,
        new_state.valvex,
        dt,
        config.valvetau,
        exp=exp,
    )

    F_total = state.Ftotal
    _, dPpump = pump_head_and_dP(
        F_total,
        new_state.spumps,
        config.dens,
        sqrt=sqrt,
    )

    for line in range(3):
        new_state.F[line] = flow_rate_from_valve(
            new_state.valvex[line],
            config.Cv,
            dPpump,
            config.G,
            new_state.flowaest[line],
            config.Flowb,
            sqrt=sqrt,
        )
        new_state.Mdot[line] = config.dens * new_state.F[line]

    new_state.Ftotal = float(np.sum(new_state.F))
    new_state.Mdottotal = float(np.sum(new_state.Mdot))

    for line in range(3):
        Ta_line, PipeT_line = thermal_line_step(
            state.Tb[line],
            config.initial_Tin,
            new_state.Mdot[line],
            config.R,
            config.dz,
            dt,
            new_state.Irad1,
            config.MirrorWidth,
            new_state.eff1[line],
            config.hamb,
            config.Tamb,
            state.PipeT[line],
            config.Dispersion,
            method="B" if config.use_backward_diff else "F",
            rho_func=rho_func,
            hinside_func=hinside_func,
            exp=exp,
            pi=pi,
        )
        new_state.Ta[line] = Ta_line
        new_state.PipeT[line] = PipeT_line
        new_state.Tb[line] = Ta_line

    return new_state


def measure_step(
    state: "SimulationState",
    config: "SimulationConfig",
    dt: float,
    rng: np.random.Generator,
) -> "SimulationState":
    new_state = copy.deepcopy(state)
    measured_noise = rng.normal(scale=config.noise_std, size=3)
    new_state.Fmeas = 0.95 * new_state.F * (1.0 + measured_noise)
    new_state.T2meas = np.array([new_state.Ta[line, -1] for line in range(3)])
    new_state.T1meas = np.array([new_state.Ta[line, -1] for line in range(3)])
    new_state.Fmeasfilt = 0.9 * new_state.Fmeas + 0.1 * new_state.Fmeasfilt
    return new_state


def control_step(
    state: "SimulationState", config: "SimulationConfig", dt: float
) -> "SimulationState":
    return copy.deepcopy(state)


def evaluate_step(
    state: "SimulationState", config: "SimulationConfig"
) -> "SimulationState":
    return copy.deepcopy(state)


def record_history(state: "SimulationState") -> "SimulationState":
    new_state = copy.deepcopy(state)
    new_state.history["simtime"].append(new_state.simtime)
    new_state.history["T1"].append(float(np.mean(new_state.Ta[:, -1])))
    new_state.history["T2"].append(float(np.mean(new_state.Ta[:, -1])))
    new_state.history["F_total"].append(float(new_state.Ftotal))
    new_state.history["pump_speed"].append(float(new_state.spumps))
    return new_state


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
    Irad: float = 0.95
    Irad1: float = 0.95
    eff: float = 0.8
    initial_Tin: float = 280.0
    initial_T1SP: float = 360.0
    initial_spump: float = 0.8
    noise_std: float = 0.05
    use_backward_diff: bool = True
    dt: float = 0.1
    exp: Callable[[Any], Any] = np.exp
    sqrt: Callable[[Any], Any] = np.sqrt
    log: Callable[[Any], Any] = np.log
    pi: float = np.pi
    rho_func: Callable[[Any], Any] = rho
    hinside_func: Callable[..., Any] = hinside

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
        self.state = process_step(self.state, self.config, dt)
        self.state = measure_step(self.state, self.config, dt, self.rng)
        self.state = control_step(self.state, self.config, dt)
        self.state = evaluate_step(self.state, self.config)
        self.state = record_history(self.state)

    def set_spump_target(self, value: float):
        self.state.spumpstarg = np.clip(value, 0.0, 1.0)
