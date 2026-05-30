import numpy as np
import pytest
from pathlib import Path
import yaml

from solar_collector.model import (
    fluid_properties,
    flow_rate_from_valve,
    hinside,
    pump_head_and_dP,
    rho,
    pump_speed_update,
    stochastic_disturbance,
    steady_state_exit_temperature,
    thermal_line_step,
    valve_characteristic,
    valve_state_update,
)

DATA_PATH = Path(__file__).parent
DATA = yaml.safe_load((DATA_PATH / "test_data.yml").read_text())


def assert_close(actual, expected, rel=1e-9, abs=1e-12):
    assert actual == pytest.approx(expected, rel=rel, abs=abs)


def test_rho_from_yaml():
    entry = DATA["rho"][0]
    assert_close(rho(entry["localT"]), entry["expected"])


def test_fluid_properties_from_yaml():
    entry = DATA["fluid_properties"][0]
    dens, cp, k, visc = fluid_properties(entry["localT"])
    assert_close(dens, entry["expected"]["dens"])
    assert_close(cp, entry["expected"]["Cp"])
    assert_close(k, entry["expected"]["k"])
    assert_close(visc, entry["expected"]["visc"])


def test_hinside_from_yaml():
    entry = DATA["hinside"][0]
    assert_close(
        hinside(entry["localT"], entry["F_line"], entry["R"]),
        entry["expected"],
    )


def test_valve_characteristic_from_yaml():
    entry = DATA["valve_characteristic"][0]
    assert_close(valve_characteristic(entry["valvex"]), entry["expected"])


def test_flow_rate_from_valve_from_yaml():
    entry = DATA["flow_rate_from_valve"][0]
    assert_close(
        flow_rate_from_valve(
            entry["valvex"],
            entry["Cv"],
            entry["dPpump"],
            entry["G"],
            entry["flowaest"],
            entry["Flowb"],
        ),
        entry["expected"],
    )


def test_pump_head_and_dP_from_yaml():
    entry = DATA["pump_head_and_dP"][0]
    Fmax, dPpump = pump_head_and_dP(
        entry["Ftotal"], entry["spumps"], entry["dens"]
    )
    assert_close(Fmax, entry["expected"]["Fmax"])
    assert_close(dPpump, entry["expected"]["dPpump"])


def test_valve_state_update_from_yaml():
    entry = DATA["valve_state_update"][0]
    assert_close(
        valve_state_update(
            entry["valvextarg"],
            entry["valvex"],
            entry["dt"],
            entry["valvetau"],
        ),
        entry["expected"],
    )


def test_pump_speed_update_from_yaml():
    entry = DATA["pump_speed_update"][0]
    assert_close(
        pump_speed_update(
            entry["spumpstarg"],
            entry["spumps"],
            entry["dt"],
            entry["pumptau"],
        ),
        entry["expected"],
    )


def test_steady_state_exit_temperature_from_yaml():
    entry = DATA["steady_state_exit_temperature"][0]
    assert_close(
        steady_state_exit_temperature(
            entry["Tin"],
            entry["Iradmeas"],
            entry["MirrorWidth"],
            entry["epsilon"],
            entry["L"],
            entry["F_line"],
            entry["dens"],
            entry["Cp"],
        ),
        entry["expected"],
    )


def test_stochastic_disturbance_from_yaml():
    entry = DATA["stochastic_disturbance"][0]
    assert_close(
        stochastic_disturbance(
            entry["prev"],
            entry["lam"],
            entry["sigma"],
            entry["random_pair"],
        ),
        entry["expected"],
    )


def test_thermal_line_step_from_yaml():
    entry = DATA["thermal_line_step"][0]
    Tb = np.array(entry["Tb"])
    PipeT = np.array(entry["PipeT"])
    expected_Ta = np.array(entry["expected"]["Ta"])
    expected_PipeT = np.array(entry["expected"]["PipeT"])
    Ta, PipeT_new = thermal_line_step(
        Tb,
        entry["Tin1"],
        entry["Mdot_line"],
        entry["R"],
        entry["dz"],
        entry["dt"],
        entry["Irad1"],
        entry["MirrorWidth"],
        entry["eff1"],
        entry["hamb"],
        entry["Tamb"],
        PipeT,
        entry["Dispersion"],
        method=entry["method"],
    )
    np.testing.assert_allclose(Ta, expected_Ta, rtol=1e-6, atol=1e-9)
    np.testing.assert_allclose(PipeT_new, expected_PipeT, rtol=1e-6, atol=1e-9)
