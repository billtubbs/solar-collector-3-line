import casadi as cas
import numpy as np
import pytest

from solar_collector.casadi_model import CasadiSolarCollectorModel
from solar_collector.model import (
    line_pressure_balance_residual,
    pump_head_and_dP,
    pump_speed_update,
    valve_characteristic,
    valve_state_update,
)
from solar_collector.simulation import SimulationConfig, SimulationState


def make_initial_state(config: SimulationConfig) -> SimulationState:
    Tb = np.tile(
        np.linspace(config.initial_Tin, config.initial_Tin + 95.0, config.N),
        (3, 1),
    )
    PipeT = np.tile(
        np.linspace(
            config.initial_Tin + 40.0, config.initial_Tin + 135.0, config.N
        ),
        (3, 1),
    )
    F = np.full(3, 0.006)
    Mdot = F * config.dens
    return SimulationState(
        spumps=config.initial_spump,
        spumpstarg=config.initial_spump,
        valvex=np.full(3, 0.9),
        valvextarg=np.full(3, 0.9),
        F=F,
        Mdot=Mdot,
        Tb=Tb,
        Ta=Tb.copy(),
        PipeT=PipeT,
        eff1=np.full(3, config.eff),
        epsilonest=np.full(3, config.eff),
        valvexm=np.full(3, 0.9),
        Fmeas=np.full(3, 0.006),
        Fmeasfilt=np.full(3, 0.006),
        T1meas=np.full(3, config.initial_Tin),
        T2meas=np.full(3, config.initial_Tin),
        T2SP=np.full(3, config.initial_Tin),
        T2model=np.full(3, config.initial_Tin),
        Iterm=np.zeros(3),
        flowaest=np.full(3, 0.006),
        effdrop=np.zeros(3),
        Ftotal=float(np.sum(F)),
        Mdottotal=float(np.sum(Mdot)),
        Irad=config.Irad,
        Irad1=config.Irad1,
        eff=config.eff,
    )


def pack_state(
    model: CasadiSolarCollectorModel, state: SimulationState
) -> cas.DM:
    return model._pack_state(
        state.spumps,
        state.valvex,
        cas.DM(state.Mdot),
        cas.DM(state.Tb),
        cas.DM(state.PipeT),
    )


def pack_input(state: SimulationState, config: SimulationConfig) -> cas.DM:
    return cas.vertcat(
        state.spumpstarg,
        cas.DM(state.valvextarg),
        config.Irad,
        config.Tamb,
        config.initial_Tin,
    )


def test_casadi_model_step_pump_valve_dynamics():
    config = SimulationConfig()
    model = CasadiSolarCollectorModel(config)
    state = make_initial_state(config)
    u = pack_input(state, config)
    x0 = pack_state(model, state)

    x1 = model.F(0.0, x0, u)
    spumps_new, valvex_new, Mdot_lines_new, Tb_new, PipeT_new = (
        model._unpack_state(x1)
    )

    # Pump and valve lag dynamics are independent of the hydraulic balance
    expected_spumps = pump_speed_update(
        state.spumpstarg, state.spumps, config.dt, config.pumptau
    )
    expected_valvex = valve_state_update(
        state.valvextarg, state.valvex, config.dt, config.valvetau
    )
    assert float(spumps_new) == pytest.approx(expected_spumps, rel=1e-7)
    assert np.allclose(
        np.array(valvex_new).flatten(), expected_valvex, rtol=1e-7, atol=1e-9
    )


def test_casadi_model_hydraulic_balance():
    """Flow rates from model.F must satisfy the full per-line pressure balance."""
    config = SimulationConfig()
    model = CasadiSolarCollectorModel(config)
    state = make_initial_state(config)
    u = pack_input(state, config)
    x0 = pack_state(model, state)

    x1 = model.F(0.0, x0, u)
    spumps_new, valvex_new, Mdot_lines_new, _, _ = model._unpack_state(x1)

    F_arr = np.array(Mdot_lines_new).flatten() / config.dens
    valvex_arr = np.array(valvex_new).flatten()
    Ftotal_sol = float(F_arr.sum())
    _, dPpump = pump_head_and_dP(Ftotal_sol, float(spumps_new), config.dens)

    # Flow conservation
    assert pytest.approx(F_arr.sum(), rel=1e-6) == Ftotal_sol

    # Per-line pressure balance: dP_valve + dP_line + dP_system = dP_pump
    for i in range(model.n_lines):
        fofx_i = valve_characteristic(valvex_arr[i])
        residual = line_pressure_balance_residual(
            F_arr[i], Ftotal_sol, fofx_i,
            config.Cv, config.G, config.Flowa, config.Flowb, dPpump,
        )
        assert pytest.approx(residual, abs=1e-6) == 0.0


def test_casadi_model_output_function_returns_expected_shape():
    config = SimulationConfig()
    model = CasadiSolarCollectorModel(config)
    state = make_initial_state(config)
    x0 = pack_state(model, state)
    u = pack_input(state, config)

    y = model.H(0.0, x0, u)
    assert y.shape == (model.ny, 1)
    assert np.allclose(
        np.array(y[:model.n_lines]).flatten(),
        state.Mdot,
        rtol=1e-7,
    )
