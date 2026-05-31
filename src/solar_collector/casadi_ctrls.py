import casadi as cas
from dataclasses import dataclass


def _clip(x, lo, hi):
    return cas.if_else(x < lo, lo, cas.if_else(x > hi, hi, x))


def _max2(x, y):
    return cas.if_else(x > y, x, y)


def _where(condition, x, y):
    return cas.if_else(condition, x, y)


@dataclass
class ControllerConfig:
    """Parameters for all four VBA-derived cascade controllers.

    Defaults match the base-case spreadsheet configuration.
    """
    dt_ctrl: float = 1.0               # control interval (s)
    n_lines: int = 3
    # T1 PI (primary exit-T controller)
    T1PIGain: float = 1.5              # proportional gain
    T1PITau: float = 1000.0            # integral time constant (s)
    T2SP_lo: float = 335.0             # anti-windup lower bound on T2SP (°C)
    T2SP_hi: float = 365.0             # anti-windup upper bound on T2SP (°C)
    # T2 GMC (secondary mid-line T controller)
    GMCGain: float = 1.8               # GMC proportional gain
    tauw: float = 100.0                # GMC bias filter time constant (s)
    MirrorWidth: float = 5.76          # collector mirror aperture (m)
    L: float = 192.0                   # collector pipe length (m)
    dens: float = 671.14               # fluid density (kg/m³)
    Cp: float = 2.2                    # fluid specific heat (kJ/(kg K))
    Fdesired_lo: float = 0.001         # lower bound on Fdesired (m³/s)
    Fdesired_hi: float = 0.01          # upper bound on Fdesired (m³/s)
    # F MBC (tertiary flow/valve controller)
    Cv: float = 10.0 / 3600.0          # valve sizing coefficient
    G: float = 671.14 / 1000.0         # valve seat pressure-drop coeff
    Flowb: float = 0.5 * (4.0 / 9.0) * 5_000_000.0  # boiler/header coeff
    valveR: float = 50.0               # valve rangeability
    valvetau: float = 2.0              # valve lag time constant (s)
    MBCtauw: float = 7.5               # MBC push time constant (s)
    FpmmFiltTau: float = 3.0           # flow pmm filter time constant (s)
    valvetarg_lo: float = 0.1          # valve target lower bound
    valvetarg_hi: float = 1.0          # valve target upper bound
    # Pump PI (auxiliary pump speed controller)
    valvexSP: float = 0.9              # most-open valve setpoint
    PumpPIGain: float = 0.03           # pump PI proportional gain
    PumpPITau: float = 2.0             # pump PI integral time constant (s)
    spumpstarg_lo: float = 0.3         # pump speed target lower bound
    spumpstarg_hi: float = 1.0         # pump speed target upper bound


class T1PIController:
    """Primary PI exit-temperature controller: T1meas → T2SP setpoints.

    Mirrors the StateSpaceModelDT interface from casadi-models.

    State x  (n = n_lines)
    ────────────────────────
    Iterm1..3    integral term per line             [°C]

    Input u  (nu = 1 + n_lines + 1 = 5)
    ──────────────────────────────────────
    T1SP         exit temperature setpoint          [°C]
    T1meas1..3   measured exit temperature per line [°C]
    Tin          inlet fluid temperature            [°C]

    Output y  (ny = n_lines = 3)
    ──────────────────────────────
    T2SP1..3     mid-line temperature setpoints     [°C]

    Anti-windup: T2SP is clamped to [T2SP_lo, T2SP_hi] and Iterm is
    back-calculated so the integrator does not wind up beyond saturation.
    """

    def __init__(self, config: ControllerConfig, name: str = None):
        self.config = config
        self.name = name
        nl = config.n_lines
        self.n = nl
        self.nu = 1 + nl + 1
        self.ny = nl
        self.state_names = [f"Iterm{i+1}" for i in range(nl)]
        self.input_names = ["T1SP"] + [f"T1meas{i+1}" for i in range(nl)] + ["Tin"]
        self.output_names = [f"T2SP{i+1}" for i in range(nl)]
        self.params = {}
        self.t = cas.SX.sym("t")
        self.x = cas.SX.sym("x", self.n)
        self.u = cas.SX.sym("u", self.nu)
        self.F = cas.Function(
            "F",
            [self.t, self.x, self.u],
            [self._state_update(self.t, self.x, self.u)],
            ["t", "xk", "uk"], ["xkp1"],
        )
        self.H = cas.Function(
            "H",
            [self.t, self.x, self.u],
            [self._output_map(self.t, self.x, self.u)],
            ["t", "xk", "uk"], ["yk"],
        )

    def _unpack_state(self, x):
        return x  # Iterm[1..3]

    def _unpack_input(self, u):
        T1SP = u[0]
        T1meas = u[1: 1 + self.config.n_lines]
        Tin = u[1 + self.config.n_lines]
        return T1SP, T1meas, Tin

    def _compute(self, x, u):
        cfg = self.config
        Iterm = self._unpack_state(x)
        T1SP, T1meas, Tin = self._unpack_input(u)
        acterr = T1SP - T1meas
        Pterm = cfg.T1PIGain * acterr
        Iterm_new = Iterm + cfg.dt_ctrl * cfg.T1PIGain * acterr / cfg.T1PITau
        T2SP_raw = Tin + (T1SP - Tin) / 2.0 + Pterm + Iterm_new
        T2SP = _clip(T2SP_raw, cfg.T2SP_lo, cfg.T2SP_hi)
        # Back-calculate Iterm so integrator matches clamped output
        Iterm_final = T2SP - Tin - (T1SP - Tin) / 2.0 - Pterm
        return Iterm_final, T2SP

    def _state_update(self, t, x, u):
        Iterm_final, _ = self._compute(x, u)
        return Iterm_final

    def _output_map(self, t, x, u):
        _, T2SP = self._compute(x, u)
        return T2SP


class T2GMCController:
    """Secondary GMC mid-line temperature controller: T2SP, T2meas → Fdesired.

    Mirrors the StateSpaceModelDT interface from casadi-models.

    State x  (n = n_lines)
    ────────────────────────
    GMCbias1..3  filtered model-setpoint bias per line  [°C]

    Input u  (nu = 3*n_lines + 2 = 14 for n_lines=3)
    ──────────────────────────────────────────────────
    T2SP1..3        mid-line temperature setpoints      [°C]
    T2meas1..3      measured mid-line temperatures      [°C]
    Iradmeas        measured DNI                        [kW/m²]
    epsilonest1..3  estimated optical efficiency        [—]
    Tin             inlet fluid temperature             [°C]
    Fmeasfilt1..3   filtered flow measurements          [m³/s]

    Output y  (ny = n_lines = 3)
    ──────────────────────────────
    Fdesired1..3    desired flow rates                  [m³/s]

    The bias state is updated using an exponential filter on the
    steady-state model–setpoint mismatch, then used to augment the
    proportional feedback for a Generic Model Control (GMC) law.
    """

    def __init__(self, config: ControllerConfig, name: str = None):
        self.config = config
        self.name = name
        nl = config.n_lines
        self.n = nl
        self.nu = 4 * nl + 2
        self.ny = nl
        self.state_names = [f"GMCbias{i+1}" for i in range(nl)]
        self.input_names = (
            [f"T2SP{i+1}" for i in range(nl)]
            + [f"T2meas{i+1}" for i in range(nl)]
            + ["Iradmeas"]
            + [f"epsilonest{i+1}" for i in range(nl)]
            + ["Tin"]
            + [f"Fmeasfilt{i+1}" for i in range(nl)]
        )
        self.output_names = [f"Fdesired{i+1}" for i in range(nl)]
        self.params = {}
        self.t = cas.SX.sym("t")
        self.x = cas.SX.sym("x", self.n)
        self.u = cas.SX.sym("u", self.nu)
        self.F = cas.Function(
            "F",
            [self.t, self.x, self.u],
            [self._state_update(self.t, self.x, self.u)],
            ["t", "xk", "uk"], ["xkp1"],
        )
        self.H = cas.Function(
            "H",
            [self.t, self.x, self.u],
            [self._output_map(self.t, self.x, self.u)],
            ["t", "xk", "uk"], ["yk"],
        )

    def _unpack_state(self, x):
        return x  # GMCbias[1..3]

    def _unpack_input(self, u):
        nl = self.config.n_lines
        T2SP       = u[0:nl]
        T2meas     = u[nl: 2*nl]
        Iradmeas   = u[2*nl]
        epsilonest = u[2*nl + 1: 3*nl + 1]
        Tin        = u[3*nl + 1]
        Fmeasfilt  = u[3*nl + 2: 4*nl + 2]
        return T2SP, T2meas, Iradmeas, epsilonest, Tin, Fmeasfilt

    def _compute(self, x, u):
        cfg = self.config
        GMCbias = self._unpack_state(x)
        T2SP, T2meas, Iradmeas, epsilonest, Tin, Fmeasfilt = self._unpack_input(u)

        solar_gain = Iradmeas * cfg.MirrorWidth * epsilonest * (cfg.L / 2.0)
        # Steady-state model: T2 given current flow (inverted for T2SPBias)
        T2SSmodel = Tin + solar_gain / (cfg.dens * cfg.Cp * Fmeasfilt)
        GMCm_bias = T2SSmodel - T2SP   # model–setpoint mismatch
        GMClam = 1.0 - cas.exp(-cfg.dt_ctrl / cfg.tauw)
        GMCbias_new = GMClam * GMCm_bias + (1.0 - GMClam) * GMCbias
        Pterm = cfg.GMCGain * (T2SP - T2meas)
        T2SP_eff = T2SP + Pterm + GMCbias_new
        Fdesired_raw = solar_gain / (cfg.dens * cfg.Cp * (T2SP_eff - Tin))
        Fdesired = _clip(Fdesired_raw, cfg.Fdesired_lo, cfg.Fdesired_hi)
        return GMCbias_new, Fdesired

    def _state_update(self, t, x, u):
        GMCbias_new, _ = self._compute(x, u)
        return GMCbias_new

    def _output_map(self, t, x, u):
        _, Fdesired = self._compute(x, u)
        return Fdesired


class FMBCController:
    """Tertiary model-based flow controller: Fdesired → valve targets.

    Mirrors the StateSpaceModelDT interface from casadi-models.

    State x  (n = 2*n_lines = 6)
    ───────────────────────────────
    valvexm1..3  model valve positions (post-lag, current step)  [0.1, 1.0]
    Fpmm1..3     filtered flow model–process mismatch per line   [m³/s]

    Input u  (nu = 3*n_lines + 1 = 10 for n_lines=3)
    ──────────────────────────────────────────────────
    Fdesired1..3   desired flow rates from T2 controller  [m³/s]
    Fmeasfilt1..3  filtered measured flow rates           [m³/s]
    dPpump         pump pressure rise                     [kPa]
    flowaest1..3   estimated line pressure-drop coeff     [kPa s²/m⁶]

    Output y  (ny = n_lines = 3)
    ──────────────────────────────
    valvextarg1..3  valve stem targets                    [0.1, 1.0]

    The stored valvexm is the model valve position already lagged toward
    the previous step's valvextarg (VBA FModel step).  F computes the
    current output valvextarg and then lags valvexm toward it for the
    next step.
    """

    def __init__(self, config: ControllerConfig, name: str = None):
        self.config = config
        self.name = name
        nl = config.n_lines
        self.n = 2 * nl
        self.nu = 3 * nl + 1
        self.ny = nl
        self.state_names = (
            [f"valvexm{i+1}" for i in range(nl)]
            + [f"Fpmm{i+1}" for i in range(nl)]
        )
        self.input_names = (
            [f"Fdesired{i+1}" for i in range(nl)]
            + [f"Fmeasfilt{i+1}" for i in range(nl)]
            + ["dPpump"]
            + [f"flowaest{i+1}" for i in range(nl)]
        )
        self.output_names = [f"valvextarg{i+1}" for i in range(nl)]
        self.params = {}
        self.t = cas.SX.sym("t")
        self.x = cas.SX.sym("x", self.n)
        self.u = cas.SX.sym("u", self.nu)
        self.F = cas.Function(
            "F",
            [self.t, self.x, self.u],
            [self._state_update(self.t, self.x, self.u)],
            ["t", "xk", "uk"], ["xkp1"],
        )
        self.H = cas.Function(
            "H",
            [self.t, self.x, self.u],
            [self._output_map(self.t, self.x, self.u)],
            ["t", "xk", "uk"], ["yk"],
        )

    def _unpack_state(self, x):
        nl = self.config.n_lines
        return x[:nl], x[nl:]  # valvexm, Fpmm

    def _unpack_input(self, u):
        nl = self.config.n_lines
        Fdesired  = u[:nl]
        Fmeasfilt = u[nl: 2*nl]
        dPpump    = u[2*nl]
        flowaest  = u[2*nl + 1: 3*nl + 1]
        return Fdesired, Fmeasfilt, dPpump, flowaest

    def _compute(self, x, u):
        cfg = self.config
        valvexm, Fpmm = self._unpack_state(x)
        Fdesired, Fmeasfilt, dPpump, flowaest = self._unpack_input(u)

        # FModel: compute model flow from current valvexm
        fofxm = cfg.valveR ** (valvexm - 1.0)
        Fm = cfg.Cv * fofxm * cas.sqrt(
            dPpump / (cfg.G + (flowaest + 9.0 * cfg.Flowb) * (cfg.Cv * fofxm) ** 2)
        )

        # Update Fpmm (filtered flow mismatch)
        Fpmmlambda = 1.0 - cas.exp(-cfg.dt_ctrl / cfg.FpmmFiltTau)
        Fpmm_new = Fpmmlambda * (Fmeasfilt - Fm) + (1.0 - Fpmmlambda) * Fpmm

        # Invert valve equation for desired valve position
        Fdes_corrected = Fdesired - Fpmm_new
        denom = dPpump / Fdes_corrected ** 2 - flowaest - 9.0 * cfg.Flowb
        fofxdesired = _where(denom > 0.0, cas.sqrt(cfg.G / cfg.Cv ** 2 / denom), 1.0)
        valvexSP = 1.0 + cas.log(fofxdesired) / cas.log(cfg.valveR)

        # MBC push: faster-than-valve move toward steady-state target
        valvextarg = _clip(
            cfg.valvetau / cfg.MBCtauw * (valvexSP - valvexm) + valvexm,
            cfg.valvetarg_lo,
            cfg.valvetarg_hi,
        )

        # Update valvexm for next step by lagging toward this valvextarg
        alpha = cas.exp(-cfg.dt_ctrl / cfg.valvetau)
        valvexm_new = _clip(
            alpha * valvexm + (1.0 - alpha) * valvextarg,
            cfg.valvetarg_lo,
            cfg.valvetarg_hi,
        )

        return valvexm_new, Fpmm_new, valvextarg

    def _pack_state(self, valvexm, Fpmm):
        return cas.vertcat(valvexm, Fpmm)

    def _state_update(self, t, x, u):
        valvexm_new, Fpmm_new, _ = self._compute(x, u)
        return self._pack_state(valvexm_new, Fpmm_new)

    def _output_map(self, t, x, u):
        _, _, valvextarg = self._compute(x, u)
        return valvextarg


class PumpPIController:
    """Auxiliary pump PI controller: max model valve position → pump speed target.

    Mirrors the StateSpaceModelDT interface from casadi-models.

    State x  (n = 1)
    ──────────────────
    pumpintegral   PI integral term  [—]

    Input u  (nu = n_lines = 3)
    ─────────────────────────────
    valvexm1..3   model valve positions from FMBCController  [0.1, 1.0]

    Output y  (ny = 1)
    ────────────────────
    spumpstarg    pump speed target  [0.3, 1.0]

    Asymmetric gain: 5× faster response when the most-open valve exceeds
    the setpoint (pump needs to speed up) than when it is below (slow down).
    """

    def __init__(self, config: ControllerConfig, name: str = None):
        self.config = config
        self.name = name
        nl = config.n_lines
        self.n = 1
        self.nu = nl
        self.ny = 1
        self.state_names = ["pumpintegral"]
        self.input_names = [f"valvexm{i+1}" for i in range(nl)]
        self.output_names = ["spumpstarg"]
        self.params = {}
        self.t = cas.SX.sym("t")
        self.x = cas.SX.sym("x", self.n)
        self.u = cas.SX.sym("u", self.nu)
        self.F = cas.Function(
            "F",
            [self.t, self.x, self.u],
            [self._state_update(self.t, self.x, self.u)],
            ["t", "xk", "uk"], ["xkp1"],
        )
        self.H = cas.Function(
            "H",
            [self.t, self.x, self.u],
            [self._output_map(self.t, self.x, self.u)],
            ["t", "xk", "uk"], ["yk"],
        )

    def _compute(self, x, u):
        cfg = self.config
        pumpintegral = x[0]
        valvexm = u

        maxvalvexm = _max2(_max2(valvexm[0], valvexm[1]), valvexm[2])
        valvexerr = maxvalvexm - cfg.valvexSP
        # Asymmetric gain: 5× faster when valve is too open (pump too slow)
        pumppropor = _where(
            valvexerr > 0.0,
            5.0 * cfg.PumpPIGain * valvexerr,
            cfg.PumpPIGain * valvexerr,
        )
        pumpintegral_new = pumpintegral + cfg.dt_ctrl * pumppropor / cfg.PumpPITau
        spumpstarg = _clip(
            pumppropor + pumpintegral_new, cfg.spumpstarg_lo, cfg.spumpstarg_hi
        )
        return pumpintegral_new, spumpstarg

    def _state_update(self, t, x, u):
        pumpintegral_new, _ = self._compute(x, u)
        return cas.vertcat(pumpintegral_new)

    def _output_map(self, t, x, u):
        _, spumpstarg = self._compute(x, u)
        return cas.vertcat(spumpstarg)
