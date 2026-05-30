import numpy as np

DEFAULT_EXP = np.exp
DEFAULT_LOG = np.log
DEFAULT_SQRT = np.sqrt
DEFAULT_SIN = np.sin
DEFAULT_PI = 3.14159
DEFAULT_MIN = np.minimum
DEFAULT_MAX = np.maximum
DEFAULT_CLIP = np.clip
DEFAULT_WHERE = np.where
ZERO_CELSIUS = 273.15


def clamp_temperature(
    localT,
    minT=250.0,
    maxT=500.0,
    min=DEFAULT_MIN,
    max=DEFAULT_MAX,
):
    """Clamp a local temperature value to the supported range."""
    return min(max(localT, minT), maxT)


def fluid_properties(
    localT,
    exp=DEFAULT_EXP,
    min=DEFAULT_MIN,
    max=DEFAULT_MAX,
):
    """Return fluid density, specific heat, conductivity, and viscosity."""
    localT = clamp_temperature(localT, min=min, max=max)
    localTK = localT + ZERO_CELSIUS
    fluid_dens = 960.73 + 0.11489 * localTK - 0.001082 * localTK**2
    fluid_Cp = (1108.027 + 1.70714 * localTK) / 1000.0
    fluid_k = (0.19091 - 0.0001894 * localTK) / 1000.0
    fluid_visc = exp(1636.999 / localTK) * 0.0000394059 - 0.0002115
    return fluid_dens, fluid_Cp, fluid_k, fluid_visc


def rho(localT, min=DEFAULT_MIN, max=DEFAULT_MAX):
    """Fluid density as a function of temperature in Celsius."""
    localT = clamp_temperature(localT, min=min, max=max)
    localTK = localT + ZERO_CELSIUS
    return 960.73 + 0.11489 * localTK - 0.001082 * localTK**2


def rhocp(localT, min=DEFAULT_MIN, max=DEFAULT_MAX):
    """Fluid density times heat capacity for the working fluid."""
    fluid_dens, fluid_Cp, *_ = fluid_properties(localT, min=min, max=max)
    return fluid_dens * fluid_Cp


def hinside(
    localT,
    F_line,
    R,
    exp=DEFAULT_EXP,
    log=DEFAULT_LOG,
    sqrt=DEFAULT_SQRT,
    pi=DEFAULT_PI,
    min=DEFAULT_MIN,
    max=DEFAULT_MAX,
):
    """Compute the internal heat transfer coefficient for a single line."""
    localT = clamp_temperature(localT, min=min, max=max)
    localTK = localT + ZERO_CELSIUS
    fluid_dens, fluid_Cp, fluid_k, fluid_visc = fluid_properties(
        localT, exp=exp, min=min, max=max
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
    valvex,
    Cv,
    dPpump,
    G,
    flowaest,
    Flowb,
    valveR=50.0,
    sqrt=DEFAULT_SQRT,
    where=DEFAULT_WHERE,
):
    """Compute single-line flow rate from valve position and pressure terms."""
    fofx = valve_characteristic(valvex, valveR=valveR)
    denom = G + (flowaest + 9.0 * Flowb) * (Cv * fofx) ** 2
    ratio = where(denom <= 0.0, 0.0, dPpump / denom)
    return Cv * fofx * sqrt(ratio)


def pump_head_and_dP(
    Ftotal,
    spumps,
    dens,
    sref=2970.0,
    Fmaxref=224.6293 / 3600.0,
    sqrt=DEFAULT_SQRT,
    min=DEFAULT_MIN,
):
    """Calculate pump maximum flow and pump pressure drop for a given speed."""
    speed = spumps * sref
    Fmax = Fmaxref * (speed / sref)
    hmaxref = 128.0 * dens * 9.807 / 1000.0
    hmax = hmaxref * (speed / sref) ** 2
    Ftotal_limited = min(Ftotal, Fmax)
    dPpump = hmax * (1.0 - (Ftotal_limited / Fmax) ** 4.346734)
    return Fmax, dPpump


def valve_state_update(
    valvextarg,
    valvex,
    dt,
    valvetau,
    exp=DEFAULT_EXP,
    clip=DEFAULT_CLIP,
):
    """Update the current valve position with first-order lag dynamics."""
    valvex_new = (1.0 - exp(-dt / valvetau)) * valvextarg + exp(
        -dt / valvetau
    ) * valvex
    return clip(valvex_new, 0.1, 1.0)


def pump_speed_update(spumpstarg, spumps, dt, pumptau, exp=DEFAULT_EXP):
    """Update pump speed with first-order lag dynamics."""
    return (1.0 - exp(-dt / pumptau)) * spumpstarg + exp(
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


def _vector_length(vector):
    """Return the length of a 1D or 2D vector for NumPy and CasADi arrays."""
    if hasattr(vector, "size1") and hasattr(vector, "size2"):
        size1 = vector.size1()
        size2 = vector.size2()
        if size1 == 1:
            return int(size2)
        if size2 == 1:
            return int(size1)
        return int(size1)

    if hasattr(vector, "shape"):
        shape = vector.shape
        if isinstance(shape, tuple):
            if len(shape) == 1:
                return int(shape[0])
            if len(shape) == 2:
                if shape[0] == 1:
                    return int(shape[1])
                if shape[1] == 1:
                    return int(shape[0])
                return int(shape[0])

    return len(vector)


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
    min=DEFAULT_MIN,
    max=DEFAULT_MAX,
):
    """Advance one fluid line through a single thermal timestep."""
    N = _vector_length(Tb)
    assert N >= 2, "Temperature vector must have at least two segments"
    ProcessF = pi * R**2 * dz
    ProcessD = Irad1 * MirrorWidth * eff1 / (pi * R)
    Ta = Tb * 0
    PipeT_new = PipeT * 0
    rho_Tb = rho_func(Tb)

    def pipe_temperature(old_pipeT, localT, local_rho):
        local_h = hinside_func(localT, Mdot_line / local_rho, R, exp=exp)
        return (1.0 - exp(-dt / 10.0)) * (
            (ProcessD + local_h * localT + hamb * Tamb) / (local_h + hamb)
        ) + exp(-dt / 10.0) * old_pipeT

    PipeT_new[0] = pipe_temperature(PipeT[0], Tb[0], rho_Tb[0])
    rho_xCp = rhocp(Tb[0], min=min, max=max)
    ProcessE = R * rho_xCp
    ProcessC = Dispersion / (rho_xCp * dz**2)
    Ta[0] = Tb[0] + dt * (
        (
            (hinside_func(Tb[0], Mdot_line / rho_Tb[0], R, exp=exp) / ProcessE)
            * (PipeT_new[0] - Tb[0])
        )
        - (Mdot_line / rho(Tb[0], min=min, max=max) / ProcessF)
        * (Tb[0] - Tin1)
        + ProcessC * (Tb[1] - 2.0 * Tb[0] + Tin1)
    )

    for k in range(1, N - 1):
        PipeT_new[k] = pipe_temperature(PipeT[k], Tb[k], rho_Tb[k])
        rho_xCp = rhocp(Tb[k], min=min, max=max)
        ProcessE = R * rho_xCp
        ProcessC = Dispersion / (rho_xCp * dz)
        rho_value = rho(Tb[k], min=min, max=max)
        if method == "B":
            Ta[k] = Tb[k] + dt * (
                (
                    (
                        hinside_func(Tb[k], Mdot_line / rho_Tb[k], R, exp=exp)
                        / ProcessE
                    )
                    * (PipeT_new[k] - Tb[k])
                )
                - (Mdot_line / rho_value / ProcessF) * (Tb[k] - Tb[k - 1])
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
                - (Mdot_line / rho_value / ProcessF)
                * (Tb[k + 1] - Tb[k - 1])
                / 2.0
                + ProcessC * (Tb[k + 1] - 2.0 * Tb[k] + Tb[k - 1])
            )

    PipeT_new[N - 1] = pipe_temperature(PipeT[N - 1], Tb[N - 1], rho_Tb[N - 1])
    rho_xCp = rhocp(Tb[N - 1], min=min, max=max)
    ProcessE = R * rho_xCp
    ProcessC = Dispersion / (rho_xCp * dz)
    rho_value_N = rho(Tb[N - 1], min=min, max=max)
    Ta[N - 1] = Tb[N - 1] + dt * (
        (
            (
                hinside_func(Tb[N - 1], Mdot_line / rho_Tb[N - 1], R, exp=exp)
                / ProcessE
            )
            * (PipeT_new[N - 1] - Tb[N - 1])
        )
        - (Mdot_line / rho_value_N / ProcessF) * (Tb[N - 1] - Tb[N - 2])
        + ProcessC * (-Tb[N - 1] + Tb[N - 2])
    )

    return Ta, PipeT_new
