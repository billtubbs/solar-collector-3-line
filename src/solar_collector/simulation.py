"""Simulation functions for the solar collector plant.

The primary entry point is :func:`simulate`, which builds a closed-loop
CasADi simulation function from a plant model and a controller model.
:func:`make_open_loop_simulation` builds the simpler open-loop variant.

Both return compiled CasADi Functions that can be evaluated numerically
or differentiated through for gradient-based optimisation.

Dataclasses
-----------
SimulationConfig
    Physical and numerical configuration for the plant and controllers.
SimulationState
    Legacy mutable state snapshot (retained for test compatibility).

Functions
---------
simulate
    Build a closed-loop n-step CasADi simulation function.
make_open_loop_simulation
    Build an open-loop n-step CasADi simulation function.
"""

import casadi as cas
import numpy as np
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .model import hinside, rho


def simulate(plant, controller, nT, nd, measurement_fn, name=None):
    """Build a closed-loop n-step CasADi simulation function.

    Constructs a CasADi Function that simulates a discrete-time feedback
    loop for nT steps.  At each step k the computation is:

      1. u_ctrl[k]     = measurement_fn(x_plant[k], d[k])
      2. u_plant[k]    = H_ctrl(t[k], x_ctrl[k], u_ctrl[k])
      3. y_plant[k]    = H_plant(t[k], x_plant[k], u_plant[k])
      4. x_plant[k+1]  = F_plant(t[k], x_plant[k], u_plant[k])
      5. x_ctrl[k+1]   = F_ctrl(t[k], x_ctrl[k], u_ctrl[k])

    Parameters
    ----------
    plant : StateSpaceModelDT-compatible object
        Discrete-time plant model (e.g. CasadiSolarCollectorModel) with
        attributes ``F``, ``H``, ``n``, ``nu``, ``ny``, ``params``.
    controller : StateSpaceModelDT-compatible object
        Discrete-time controller model (e.g. T1PIController) with the
        same interface.
    nT : int
        Number of simulation steps.
    nd : int
        Dimension of the disturbance / exogenous input vector d[k].
    measurement_fn : callable(x_plant, d_k) -> u_ctrl
        Maps the plant state vector and the current disturbance vector
        to the controller input vector.  Must be written using CasADi
        operations so the computation graph can be traced symbolically.
    name : str, optional
        Name for the returned CasADi function.  Defaults to
        ``'closed_loop_sim_{nT}_steps'``.

    Returns
    -------
    cas.Function
        Signature: ``(t_eval, D, x0) -> (X, Y)``

        Inputs:
          ``t_eval``  (nT+1,)                 time vector
          ``D``       (nT, nd)                disturbance matrix
          ``x0``      (n_plant + n_ctrl,)     initial combined state

        Outputs:
          ``X``  (nT+1, n_plant + n_ctrl)  combined state trajectory
          ``Y``  (nT+1, ny_plant)          plant output trajectory

        The combined state ``X`` can be split into plant and controller
        parts using ``X[:, :plant.n]`` and ``X[:, plant.n:]``.
    """
    if name is None:
        name = f"closed_loop_sim_{nT}_steps"

    n_p = plant.n
    n_c = controller.n

    t_eval = cas.SX.sym("t_eval", nT + 1)
    D = cas.SX.sym("D", nT, nd)
    x0 = cas.SX.sym("x0", n_p + n_c)

    X = [x0.T]
    Y = []

    xk = x0
    tk = t_eval[0]
    u_plant_k = cas.SX.zeros(plant.nu)

    for k in range(nT):
        x_pk = xk[:n_p]
        x_ck = xk[n_p:]
        d_k = D[k, :].T

        u_ctrl_k = measurement_fn(x_pk, d_k)
        u_plant_k = controller.H(
            tk, x_ck, u_ctrl_k, *controller.params.values()
        )
        y_pk = plant.H(tk, x_pk, u_plant_k, *plant.params.values())

        x_pkp1 = plant.F(tk, x_pk, u_plant_k, *plant.params.values())
        x_ckp1 = controller.F(tk, x_ck, u_ctrl_k, *controller.params.values())

        xkp1 = cas.vertcat(x_pkp1, x_ckp1)
        X.append(xkp1.T)
        Y.append(y_pk.T)
        tk = t_eval[k + 1]
        xk = xkp1

    # Final output at the terminal state using the last inputs
    y_final = plant.H(tk, xk[:n_p], u_plant_k, *plant.params.values())
    Y.append(y_final.T)

    return cas.Function(
        name,
        [t_eval, D, x0],
        [cas.vcat(X), cas.vcat(Y)],
        ["t_eval", "D", "x0"],
        ["X", "Y"],
    )


def make_open_loop_simulation(plant, nT, name=None):
    """Build an open-loop n-step CasADi simulation function.

    Equivalent to ``make_n_step_simulation_function_from_model`` in the
    casadi-models package.  Inputs are provided externally at every step.

    Parameters
    ----------
    plant : StateSpaceModelDT-compatible object
        Discrete-time model with ``F``, ``H``, ``n``, ``nu``, ``ny``,
        ``params``.
    nT : int
        Number of simulation steps.
    name : str, optional
        Name for the returned CasADi function.

    Returns
    -------
    cas.Function
        Signature: ``(t_eval, U, x0) -> (X, Y)``

        Inputs:
          ``t_eval``  (nT+1,)   time vector
          ``U``       (nT, nu)  input matrix
          ``x0``      (n,)      initial state

        Outputs:
          ``X``  (nT+1, n)   state trajectory
          ``Y``  (nT+1, ny)  output trajectory
    """
    if name is None:
        name = f"{plant.F.name()}_sim_{nT}_steps"

    t_eval = cas.SX.sym("t_eval", nT + 1)
    U = cas.SX.sym("U", nT, plant.nu)
    x0 = cas.SX.sym("x0", plant.n)

    X = [x0.T]
    Y = []
    xk = x0
    tk = t_eval[0]
    uk = cas.SX.zeros(plant.nu)

    for k in range(nT):
        uk = U[k, :].T
        xkp1 = plant.F(tk, xk, uk, *plant.params.values())
        yk = plant.H(tk, xk, uk, *plant.params.values())
        X.append(xkp1.T)
        Y.append(yk.T)
        tk = t_eval[k + 1]
        xk = xkp1

    yk = plant.H(tk, xk, uk, *plant.params.values())
    Y.append(yk.T)

    return cas.Function(
        name,
        [t_eval, U, x0, *plant.params.values()],
        [cas.vcat(X), cas.vcat(Y)],
        ["t_eval", "U", "x0", *plant.params.keys()],
        ["X", "Y"],
    )


@dataclass
class SimulationConfig:
    """Physical and numerical configuration for the solar collector plant."""

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
    """Full mutable state snapshot (retained for test compatibility)."""

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
