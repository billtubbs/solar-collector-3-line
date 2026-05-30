
import casadi as cas
import numpy as np
import pytest

from solar_collector.casadi_model import CasadiSolarCollectorModel
from solar_collector.simulation import SimulationConfig, SimulationState, process_step


def make_initial_state(config: SimulationConfig) -> SimulationState:
    Tb = np.tile(
        np.linspace(config.initial_Tin, config.initial_Tin + 95.0, config.N),
        (3, 1),
    )
    PipeT = np.tile(
        np.linspace(config.initial_Tin + 40.0, config.initial_Tin + 135.0, config.N),
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


def pack_state(model: CasadiSolarCollectorModel, state: SimulationState) -> cas.DM:
    return model._pack_state(
        state.spumps,
        state.valvex,
        cas.DM(state.F),
        cas.DM(state.Mdot),
        cas.DM(state.Tb),
        cas.DM(state.PipeT),
    )


def pack_input(state: SimulationState) -> cas.DM:
    return cas.vertcat(state.spumpstarg, cas.DM(state.valvextarg))


def test_casadi_model_step_matches_python_process_step():
    config = SimulationConfig()
    model = CasadiSolarCollectorModel(config)
    state = make_initial_state(config)
    u = pack_input(state)
    x0 = pack_state(model, state)

    expected_state = process_step(state, config, config.dt)

    x1 = model.F(0.0, x0, u)
    spumps_new, valvex_new, F_lines_new, Mdot_lines_new, Tb_new, PipeT_new = model._unpack_state(x1)

    assert float(spumps_new) == pytest.approx(expected_state.spumps, rel=1e-7)
    assert np.allclose(np.array(valvex_new).flatten(), expected_state.valvex, rtol=1e-7, atol=1e-9)
    assert np.allclose(np.array(F_lines_new).flatten(), expected_state.F, rtol=1e-7, atol=1e-9)
    assert np.allclose(np.array(Mdot_lines_new).flatten(), expected_state.Mdot, rtol=1e-7, atol=1e-9)
    assert np.allclose(np.array(Tb_new), expected_state.Tb, rtol=1e-7, atol=1e-9)
    assert np.allclose(np.array(PipeT_new), expected_state.PipeT, rtol=1e-7, atol=1e-9)


def test_casadi_model_output_function_returns_expected_shape():
    config = SimulationConfig()
    model = CasadiSolarCollectorModel(config)
    state = make_initial_state(config)
    x0 = pack_state(model, state)
    u = pack_input(state)

    y = model.H(0.0, x0, u)
    assert y.shape == (7, 1)
    assert float(y[0]) == pytest.approx(np.sum(state.F), rel=1e-7)
