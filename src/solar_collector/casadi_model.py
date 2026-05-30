import casadi as cas

from .model import (
    flow_rate_from_valve,
    hinside,
    pump_head_and_dP,
    pump_speed_update,
    rho,
    thermal_line_step,
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
        localT, F_line, R,
        exp=cas.exp, pi=cas.pi,
        min=_casadi_min, max=_casadi_max,
    )


class CasadiSolarCollectorModel:
    """CasADi discrete-time model for the 3-line solar collector."""

    def __init__(self, config, name: str = None):
        self.config = config
        self.name = name
        self.n_lines = 3
        self.N = config.N
        self.dt = config.dt
        self.n = 1 + 3 * self.n_lines + 2 * self.n_lines * self.N
        self.nu = 1 + self.n_lines
        self.ny = 1 + 2 * self.n_lines
        self.input_names = ["spumpstarg"] + [
            f"valvextarg{i+1}" for i in range(self.n_lines)
        ]
        self.state_names = (
            ["spumps"]
            + [f"valvex{i+1}" for i in range(self.n_lines)]
            + [f"F{i+1}" for i in range(self.n_lines)]
            + [f"Mdot{i+1}" for i in range(self.n_lines)]
            + [f"Tb{i+1}_{j+1}" for i in range(self.n_lines) for j in range(self.N)]
            + [f"PipeT{i+1}_{j+1}" for i in range(self.n_lines) for j in range(self.N)]
        )
        self.output_names = ["Ftotal"] + [
            f"F{i+1}" for i in range(self.n_lines)
        ] + [
            f"T2exit{i+1}" for i in range(self.n_lines)
        ]
        self.params = {}
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

    def _unpack_state(self, x):
        offset = 1 + 3 * self.n_lines
        spumps = x[0]
        valvex = x[1 : 1 + self.n_lines]
        F_lines = x[1 + self.n_lines : 1 + 2 * self.n_lines]
        Mdot_lines = x[1 + 2 * self.n_lines : 1 + 3 * self.n_lines]
        Tb_flat = x[offset : offset + self.n_lines * self.N]
        PipeT_flat = x[offset + self.n_lines * self.N :]
        Tb = cas.reshape(Tb_flat, self.n_lines, self.N)
        PipeT = cas.reshape(PipeT_flat, self.n_lines, self.N)
        return spumps, valvex, F_lines, Mdot_lines, Tb, PipeT

    def _unpack_input(self, u):
        return u[0], u[1 : 1 + self.n_lines]

    def _pack_state(self, spumps, valvex, F_lines, Mdot_lines, Tb, PipeT):
        return cas.vertcat(
            spumps,
            valvex,
            F_lines,
            Mdot_lines,
            cas.reshape(Tb, -1, 1),
            cas.reshape(PipeT, -1, 1),
        )

    def _state_update(self, t, x, u):
        spumps, valvex, F_lines, Mdot_lines, Tb, PipeT = self._unpack_state(x)
        spumpstarg, valvextarg = self._unpack_input(u)

        spumps_new = pump_speed_update(
            spumpstarg, spumps, self.dt, self.config.pumptau, exp=cas.exp
        )
        valvex_new = valve_state_update(
            valvextarg, valvex, self.dt, self.config.valvetau,
            exp=cas.exp, clip=_casadi_clip,
        )

        Ftotal = cas.sum1(F_lines)
        _, dPpump = pump_head_and_dP(
            Ftotal, spumps_new, self.config.dens, min=_casadi_min
        )

        F_lines_new = cas.vertcat(*[
            flow_rate_from_valve(
                valvex_new[i], self.config.Cv, dPpump,
                self.config.G, 0.0, self.config.Flowb,
                sqrt=cas.sqrt, where=_casadi_where,
            )
            for i in range(self.n_lines)
        ])
        Mdot_lines_new = self.config.dens * F_lines_new

        Tb_rows, PipeT_rows = [], []
        for line in range(self.n_lines):
            Ta_line, PipeT_line = thermal_line_step(
                Tb[line, :],
                self.config.initial_Tin,
                Mdot_lines_new[line],
                self.config.R,
                self.config.dz,
                self.dt,
                self.config.Irad1,
                self.config.MirrorWidth,
                self.config.eff,
                self.config.hamb,
                self.config.Tamb,
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
            F_lines_new,
            Mdot_lines_new,
            cas.vertcat(*Tb_rows),
            cas.vertcat(*PipeT_rows),
        )

    def _output_map(self, t, x, u):
        _, _, F_lines, _, Tb, _ = self._unpack_state(x)
        T2exit = Tb[:, self.N - 1]
        Ftotal = cas.sum1(F_lines)
        return cas.vertcat(Ftotal, F_lines, T2exit)
