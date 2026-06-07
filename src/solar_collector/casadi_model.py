import casadi as cas

from .model import (
    flow_rate_from_valve,
    hinside,
    line_pressure_balance_residual,
    pump_head_and_dP,
    pump_speed_update,
    rho,
    thermal_line_step,
    valve_characteristic,
    valve_state_update,
)


def _casadi_min(x, y):
    return cas.if_else(x < y, x, y)


def _casadi_max(x, y):
    return cas.if_else(x > y, x, y)


def _casadi_clip(x, lower, upper):
    return cas.if_else(x < lower, lower, cas.if_else(x > upper, upper, x))


def _casadi_where(condition, x, y):
    return cas.if_else(condition, x, y)


def _casadi_rho(T):
    return rho(T, min=_casadi_min, max=_casadi_max)


def _casadi_hinside(localT, F_line, R, **kwargs):
    return hinside(
        localT,
        F_line,
        R,
        exp=cas.exp,
        pi=cas.pi,
        min=_casadi_min,
        max=_casadi_max,
    )


class CasadiSolarCollectorModel:
    """CasADi discrete-time model for the 3-line parabolic solar collector.

    Mirrors the StateSpaceModelDT interface from the casadi-models package
    (duck-type compatible; no hard dependency on that package).

    State vector x  (n = 1 + 2*n_lines + 2*n_lines*N elements)
    ─────────────────────────────────────────────────────────────
    spumps           pump speed fraction                          [0, 1]
    valvex1..3       valve stem positions per line                [0.1, 1.0]
    Mdot1..3         mass flow rate per line                      [kg/s]
    Tb{i}_{k}        fluid temperature at segment k, line i       [°C]
    PipeT{i}_{k}     pipe wall temperature at segment k, line i   [°C]

    Input vector u  (nu = 1 + n_lines + 3 elements)
    ─────────────────────────────────────────────────
    spumpstarg       pump speed target                            [0, 1]
    valvextarg1..3   valve stem targets per line                  [0.1, 1.0]
    Irad             direct normal irradiance                     [kW/m²]
    Tamb             ambient temperature                          [°C]
    Tin              collector inlet fluid temperature            [°C]

    Output vector y  (ny = n_lines + n_lines*N elements)
    ─────────────────────────────────────────────────────
    Mdot1..3         per-line mass flow rates                     [kg/s]
    Tb{i}_{k}        fluid temperature at segment k, line i       [°C]

    Volumetric flow at any axial position can be derived post-hoc as
    F_i(k) = Mdot_i / rho(Tb_i_k).  Exit temperatures are Tb{i}_N.

    CasADi Functions
    ─────────────────
    F(t, xk, uk) -> xkp1   discrete-time state transition
    H(t, xk, uk) -> yk      output map

    The hydraulic balance is solved at each step by a CasADi Newton rootfinder
    embedded in the state-update graph, replacing the VBA's successive-substitution
    loop.  The rootfinder solves the full 4-variable system [Ftotal, F_1, F_2, F_3]
    using the correct per-line pressure balance (VBA line 540):
      dP_valve + dP_line(F_i^1.9) + dP_system(Ftotal^1.9) = dP_pump.
    """

    def __init__(self, config, name: str = None):
        self.config = config
        self.name = name
        self.n_lines = 3
        self.N = config.N
        self.dt = config.dt
        self.n = 1 + 2 * self.n_lines + 2 * self.n_lines * self.N
        self.nu = 1 + self.n_lines + 3  # MV + disturbances (Irad, Tamb, Tin)
        self.ny = self.n_lines + self.n_lines * self.N
        self.input_names = (
            ["spumpstarg"]
            + [f"valvextarg{i + 1}" for i in range(self.n_lines)]
            + ["Irad", "Tamb", "Tin"]
        )
        self.state_names = (
            ["spumps"]
            + [f"valvex{i + 1}" for i in range(self.n_lines)]
            + [f"Mdot{i + 1}" for i in range(self.n_lines)]
            + [
                f"Tb{i + 1}_{j + 1}"
                for j in range(self.N)
                for i in range(self.n_lines)
            ]
            + [
                f"PipeT{i + 1}_{j + 1}"
                for j in range(self.N)
                for i in range(self.n_lines)
            ]
        )
        self.output_names = [f"Mdot{i + 1}" for i in range(self.n_lines)] + [
            f"Tb{i + 1}_{j + 1}"
            for j in range(self.N)
            for i in range(self.n_lines)
        ]
        self.params = {}
        self.flow_balance = self._build_flow_balance_solver()
        self.t = cas.SX.sym("t")
        self.x = cas.SX.sym("x", self.n)
        self.u = cas.SX.sym("u", self.nu)
        self.F = cas.Function(
            "F",
            [self.t, self.x, self.u],
            [self._state_update(self.t, self.x, self.u)],
            ["t", "xk", "uk"],
            ["xkp1"],
        )
        self.H = cas.Function(
            "H",
            [self.t, self.x, self.u],
            [self._output_map(self.t, self.x, self.u)],
            ["t", "xk", "uk"],
            ["yk"],
        )

    def _build_flow_balance_solver(self):
        """Return a CasADi rootfinder that solves the pump/valve hydraulic balance.

        Variables z = [Ftotal, F_1, F_2, F_3].  Parameters p = [spumps, valvex_0..2].

        Residuals (4 equations):
          r[0]   = F_1 + F_2 + F_3 - Ftotal           (flow conservation)
          r[1+i] = dP_valve_i + dP_line_i + dP_system - dP_pump  (per-line pressure balance)

        This matches the VBA plant simulation (Module1.vba line 540), where:
          dP_valve_i  = G * (F_i / (Cv * fofx_i))^2
          dP_line_i   = Flowa * F_i^1.9
          dP_system   = Flowb * Ftotal^1.9
        """
        z = cas.SX.sym("z", 1 + self.n_lines)   # [Ftotal, F_1, F_2, F_3]
        p = cas.SX.sym("p", 1 + self.n_lines)   # [spumps, valvex_1, valvex_2, valvex_3]
        Ftotal = z[0]
        F_lines = z[1:]
        spumps_p = p[0]
        valvex_p = p[1:]

        _, dPpump = pump_head_and_dP(
            Ftotal, spumps_p, self.config.dens, min=_casadi_min, max=_casadi_max
        )
        residuals = [cas.sum1(F_lines) - Ftotal]
        for i in range(self.n_lines):
            fofx_i = valve_characteristic(valvex_p[i])
            residuals.append(line_pressure_balance_residual(
                F_lines[i], Ftotal, fofx_i,
                self.config.Cv, self.config.G, self.config.Flowa, self.config.Flowb,
                dPpump,
            ))
        rfp = cas.Function("rfp", [z, p], [cas.vertcat(*residuals)])
        return cas.rootfinder("flow_balance", "newton", rfp)

    def _unpack_state(self, x):
        offset = 1 + 2 * self.n_lines
        spumps = x[0]
        valvex = x[1 : 1 + self.n_lines]
        Mdot_lines = x[1 + self.n_lines : 1 + 2 * self.n_lines]
        Tb_flat = x[offset : offset + self.n_lines * self.N]
        PipeT_flat = x[offset + self.n_lines * self.N :]
        Tb = cas.reshape(Tb_flat, self.n_lines, self.N)
        PipeT = cas.reshape(PipeT_flat, self.n_lines, self.N)
        return spumps, valvex, Mdot_lines, Tb, PipeT

    def _unpack_input(self, u):
        spumpstarg = u[0]
        valvextarg = u[1 : 1 + self.n_lines]
        Irad = u[1 + self.n_lines]
        Tamb = u[2 + self.n_lines]
        Tin = u[3 + self.n_lines]
        return spumpstarg, valvextarg, Irad, Tamb, Tin

    def _pack_state(self, spumps, valvex, Mdot_lines, Tb, PipeT):
        return cas.vertcat(
            spumps,
            valvex,
            Mdot_lines,
            cas.reshape(Tb, -1, 1),
            cas.reshape(PipeT, -1, 1),
        )

    def _state_update(self, t, x, u):
        spumps, valvex, Mdot_lines, Tb, PipeT = self._unpack_state(x)
        spumpstarg, valvextarg, Irad, Tamb, Tin = self._unpack_input(u)

        spumps_new = pump_speed_update(
            spumpstarg, spumps, self.dt, self.config.pumptau, exp=cas.exp
        )
        valvex_new = valve_state_update(
            valvextarg,
            valvex,
            self.dt,
            self.config.valvetau,
            exp=cas.exp,
            clip=_casadi_clip,
        )

        # Initial guess for [Ftotal, F_1, F_2, F_3]; floor prevents zero-flow
        # singularity in the Jacobian of F^1.9 at the first step.
        F_i_init = [
            _casadi_max(Mdot_lines[i] / self.config.dens, 1e-6)
            for i in range(self.n_lines)
        ]
        Ftotal_init = _casadi_max(cas.sum1(Mdot_lines) / self.config.dens, 1e-6)
        z_init = cas.vertcat(Ftotal_init, *F_i_init)
        p_bal = cas.vertcat(spumps_new, valvex_new)
        z_sol = self.flow_balance(z_init, p_bal)
        F_lines_new = z_sol[1:]
        Mdot_lines_new = self.config.dens * F_lines_new

        Tb_rows, PipeT_rows = [], []
        for line in range(self.n_lines):
            Ta_line, PipeT_line = thermal_line_step(
                Tb[line, :],
                Tin,
                Mdot_lines_new[line],
                self.config.R,
                self.config.dz,
                self.dt,
                Irad,
                self.config.MirrorWidth,
                self.config.eff,
                self.config.hamb,
                Tamb,
                PipeT[line, :],
                self.config.Dispersion,
                method="B" if self.config.use_backward_diff else "F",
                rho_func=_casadi_rho,
                hinside_func=_casadi_hinside,
                exp=cas.exp,
                pi=cas.pi,
                min=_casadi_min,
                max=_casadi_max,
            )
            Tb_rows.append(Ta_line)
            PipeT_rows.append(PipeT_line)

        return self._pack_state(
            spumps_new,
            valvex_new,
            Mdot_lines_new,
            cas.vertcat(*Tb_rows),
            cas.vertcat(*PipeT_rows),
        )

    def _output_map(self, t, x, u):
        _, _, Mdot_lines, Tb, _ = self._unpack_state(x)
        return cas.vertcat(Mdot_lines, cas.reshape(Tb, -1, 1))
