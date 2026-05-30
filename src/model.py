import numpy as np

DEFAULT_EXP = np.exp
DEFAULT_LOG = np.log
DEFAULT_SQRT = np.sqrt
DEFAULT_SIN = np.sin
DEFAULT_PI = 3.14159
ZERO_CELSIUS = 273.15


def clamp_temperature(localT, minT=250.0, maxT=500.0):
    """Clamp a local temperature value to the supported range."""
    return np.minimum(np.maximum(localT, minT), maxT)


def fluid_properties(localT, exp=DEFAULT_EXP):
    """Return fluid density, specific heat, conductivity, and viscosity."""
    localT = clamp_temperature(localT)
    localTK = localT + ZERO_CELSIUS
    fluid_dens = 960.73 + 0.11489 * localTK - 0.001082 * localTK**2
    fluid_Cp = (1108.027 + 1.70714 * localTK) / 1000.0
    fluid_k = (0.19091 - 0.0001894 * localTK) / 1000.0
    fluid_visc = exp(1636.999 / localTK) * 0.0000394059 - 0.0002115
    return fluid_dens, fluid_Cp, fluid_k, fluid_visc


def rho(localT):
    """Fluid density as a function of temperature in Celsius."""
    localT = clamp_temperature(localT)
    localTK = localT + ZERO_CELSIUS
    return 960.73 + 0.11489 * localTK - 0.001082 * localTK**2


def rhocp(localT):
    """Fluid density times heat capacity for the working fluid."""
    fluid_dens, fluid_Cp, *_ = fluid_properties(localT)
    return fluid_dens * fluid_Cp


def hinside(
    localT,
    F_line,
    R,
    exp=DEFAULT_EXP,
    log=DEFAULT_LOG,
    sqrt=DEFAULT_SQRT,
    pi=DEFAULT_PI,
):
    """Compute the internal heat transfer coefficient for a single line."""
    localT = clamp_temperature(localT)
    localTK = localT + ZERO_CELSIUS
    fluid_dens, fluid_Cp, fluid_k, fluid_visc = fluid_properties(
        localT, exp=exp
    )
    gc = 1.0
    D = 2.0 * R
    Re = 4.0 * F_line * fluid_dens / (pi * D * fluid_visc * gc)
    Pr = fluid_Cp * fluid_visc * gc / fluid_k
    return (fluid_k / D) * 0.023 * Re**0.8 * Pr**0.4


def valve_characteristic(valvex, valveR=50.0):
    """Convert valve stem position to the valve flow multiplier."""
    return valveR ** (valvex - 1.0)


def flow_rate_from_valve(
    valvex, Cv, dPpump, G, flowaest, Flowb, valveR=50.0, sqrt=DEFAULT_SQRT
):
    """Compute single-line flow rate from valve position and pressure terms."""
    fofx = valve_characteristic(valvex, valveR=valveR)
    denom = G + (flowaest + 9.0 * Flowb) * (Cv * fofx) ** 2
    ratio = np.where(denom <= 0.0, 0.0, dPpump / denom)
    return Cv * fofx * sqrt(ratio)


def pump_head_and_dP(
    Ftotal,
    spumps,
    dens,
    sref=2970.0,
    Fmaxref=224.6293 / 3600.0,
    sqrt=DEFAULT_SQRT,
):
    """Calculate pump maximum flow and pump pressure drop for a given speed."""
    speed = spumps * sref
    Fmax = Fmaxref * (speed / sref)
    hmaxref = 128.0 * dens * 9.807 / 1000.0
    hmax = hmaxref * (speed / sref) ** 2
    Ftotal_limited = np.minimum(Ftotal, Fmax)
    dPpump = hmax * (1.0 - (Ftotal_limited / Fmax) ** 4.346734)
    return Fmax, dPpump


def valve_state_update(valvextarg, valvex, dt, valvetau):
    """Update the current valve position with first-order lag dynamics."""
    valvex_new = (1.0 - np.exp(-dt / valvetau)) * valvextarg + np.exp(
        -dt / valvetau
    ) * valvex
    return np.clip(valvex_new, 0.1, 1.0)


def pump_speed_update(spumpstarg, spumps, dt, pumptau):
    """Update pump speed with first-order lag dynamics."""
    return (1.0 - np.exp(-dt / pumptau)) * spumpstarg + np.exp(
        -dt / pumptau
    ) * spumps


def steady_state_exit_temperature(
    Tin, Iradmeas, MirrorWidth, epsilon, L, F_line, dens, Cp
):
    """Compute the steady-state exit temperature model for a single line."""
    return Tin + (Iradmeas * MirrorWidth * epsilon * (L / 2.0)) / (
        F_line * dens * Cp
    )


def stochastic_disturbance(
    prev,
    lam,
    sigma,
    random_pair,
    sin=DEFAULT_SIN,
    log=DEFAULT_LOG,
    pi=DEFAULT_PI,
):
    """Compute an AR(1) disturbance term with normally distributed increments."""
    r1, r2 = random_pair
    perturbation = sigma * np.sqrt(-2.0 * log(1.0 - r1)) * sin(2.0 * pi * r2)
    return (1.0 - lam) * prev + lam * perturbation


def thermal_line_step(
    Tb,
    Tin1,
    Mdot_line,
    R,
    dz,
    dt,
    Irad1,
    MirrorWidth,
    eff1,
    hamb,
    Tamb,
    PipeT,
    Dispersion,
    method="B",
    rho_func=rho,
    hinside_func=hinside,
    exp=DEFAULT_EXP,
    pi=DEFAULT_PI,
):
    """Advance one fluid line through a single thermal timestep."""
    N = len(Tb)
    assert N >= 2, "Temperature vector must have at least two segments"
    ProcessF = pi * R**2 * dz
    ProcessD = Irad1 * MirrorWidth * eff1 / (pi * R)
    Ta = np.empty_like(Tb)
    PipeT_new = np.empty_like(PipeT)
    rho_Tb = rho_func(Tb)

    def pipe_temperature(old_pipeT, localT, local_rho):
        local_h = hinside_func(localT, Mdot_line / local_rho, R, exp=exp)
        return (1.0 - np.exp(-dt / 10.0)) * (
            (ProcessD + local_h * localT + hamb * Tamb) / (local_h + hamb)
        ) + np.exp(-dt / 10.0) * old_pipeT

    PipeT_new[0] = pipe_temperature(PipeT[0], Tb[0], rho_Tb[0])
    rho_xCp = rhocp(Tb[0])
    ProcessE = R * rho_xCp
    ProcessC = Dispersion / (rho_xCp * dz**2)
    Ta[0] = Tb[0] + dt * (
        (
            (hinside_func(Tb[0], Mdot_line / rho_Tb[0], R, exp=exp) / ProcessE)
            * (PipeT_new[0] - Tb[0])
        )
        - (Mdot_line / rho(Tb[0]) / ProcessF) * (Tb[0] - Tin1)
        + ProcessC * (Tb[1] - 2.0 * Tb[0] + Tin1)
    )

    for k in range(1, N - 1):
        PipeT_new[k] = pipe_temperature(PipeT[k], Tb[k], rho_Tb[k])
        rho_xCp = rhocp(Tb[k])
        ProcessE = R * rho_xCp
        ProcessC = Dispersion / (rho_xCp * dz)
        if method == "B":
            Ta[k] = Tb[k] + dt * (
                (
                    (
                        hinside_func(Tb[k], Mdot_line / rho_Tb[k], R, exp=exp)
                        / ProcessE
                    )
                    * (PipeT_new[k] - Tb[k])
                )
                - (Mdot_line / rho(Tb[k]) / ProcessF) * (Tb[k] - Tb[k - 1])
                + ProcessC * (Tb[k + 1] - 2.0 * Tb[k] + Tb[k - 1])
            )
        else:
            Ta[k] = Tb[k] + dt * (
                (
                    (
                        hinside_func(Tb[k], Mdot_line / rho_Tb[k], R, exp=exp)
                        / ProcessE
                    )
                    * (PipeT_new[k] - Tb[k])
                )
                - (Mdot_line / rho(Tb[k]) / ProcessF)
                * (Tb[k + 1] - Tb[k - 1])
                / 2.0
                + ProcessC * (Tb[k + 1] - 2.0 * Tb[k] + Tb[k - 1])
            )

    PipeT_new[N - 1] = pipe_temperature(PipeT[N - 1], Tb[N - 1], rho_Tb[N - 1])
    rho_xCp = rhocp(Tb[N - 1])
    ProcessE = R * rho_xCp
    ProcessC = Dispersion / (rho_xCp * dz)
    Ta[N - 1] = Tb[N - 1] + dt * (
        (
            (
                hinside_func(Tb[N - 1], Mdot_line / rho_Tb[N - 1], R, exp=exp)
                / ProcessE
            )
            * (PipeT_new[N - 1] - Tb[N - 1])
        )
        - (Mdot_line / rho(Tb[N - 1]) / ProcessF) * (Tb[N - 1] - Tb[N - 2])
        + ProcessC * (-Tb[N - 1] + Tb[N - 2])
    )

    return Ta, PipeT_new
