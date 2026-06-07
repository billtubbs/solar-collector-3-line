"""Live animated simulation of the 3-line parabolic solar collector.

Displays a combined spatial profile plot (fluid and pipe-wall temperatures
vs axial position) and four scrolling time-series plots, with sliders to
adjust manipulated variables and disturbance inputs in real time.

Layout: 2 plot rows × 4 columns.
  Row 0: [combined temp profiles | exit/inlet temperatures]
  Row 1: [irradiance | pump speed | valve positions | flow rates]
  Row 2: sliders

Usage (from a run script)::

    from solar_collector.live_sim import SolarCollectorLiveSim
    live = SolarCollectorLiveSim(plant, x0, u0)
    live.run()
"""

import collections

import matplotlib.gridspec as mgridspec
import matplotlib.pyplot as plt
import matplotlib.widgets as mwidgets
import numpy as np
from matplotlib.animation import FuncAnimation

from .model import rho as _rho

_COLORS = ["tab:blue", "tab:orange", "tab:green"]
_LINE_LABELS = ["Line 1", "Line 2", "Line 3"]

# Actuator range limits — sourced from VBA controller clips (Module1.vba lines 217-218, 363-364)
_PUMP_MIN = 0.3  # spumpstarg clipped to [0.3, 1.0] in VBA
_PUMP_MAX = 1.0
_VALVE_MIN = 0.1  # valvextarg / valvex clipped to [0.1, 1.0] in VBA and valve_state_update
_VALVE_MAX = 1.0

# Temperature plot limits and reference lines (°C)
_T_PLOT_MAX = 475  # y-axis upper limit for both temperature plots
_T_MAX = 400  # maximum temperature safety limit (dark grey dashed line)
_T_SP = 395  # exit temperature setpoint (red dashed line)


class SolarCollectorLiveSim:
    """Real-time animated simulation with interactive sliders.

    Each animation frame:
      1. Advances the plant by ``steps_per_frame`` CasADi steps.
      2. Appends one record to the rolling history buffers.
      3. Redraws the spatial profiles and all time-series plots.

    Slider callbacks write directly to ``self.u``; the change takes
    effect on the next simulation step.

    Parameters
    ----------
    plant : CasadiSolarCollectorModel
    x0 : ndarray  Initial state vector.
    u0 : ndarray  Initial input vector [spumpstarg, valvextarg1..3, Irad, Tamb, Tin].
    steps_per_frame : int  Simulation steps advanced per animation frame.
    history_len : int  Maximum number of time points kept in each rolling buffer.
    frame_interval_ms : int  Target milliseconds between animation frames.
    """

    def __init__(
        self,
        plant,
        x0: np.ndarray,
        u0: np.ndarray,
        steps_per_frame: int = 1,
        history_len: int = 600,
        frame_interval_ms: int = 50,
        plot_horizon: float = 60.0,
    ):
        self.plant = plant
        self.x = x0.copy()
        self.u = u0.copy()
        self.t = 0.0
        self.steps_per_frame = steps_per_frame
        self.history_len = history_len
        self.frame_interval_ms = frame_interval_ms
        self.plot_horizon = plot_horizon

        self.n_lines = plant.n_lines
        self.N = plant.N
        self._dt = plant.dt
        cfg = plant.config

        # State vector offsets (must match casadi_model layout)
        self._tb_off = 1 + 2 * self.n_lines
        self._pt_off = self._tb_off + self.n_lines * self.N

        # Output indices for per-line exit temperatures
        self._T_exit_idx = [
            self.n_lines + (self.N - 1) * self.n_lines + i
            for i in range(self.n_lines)
        ]

        # Input indices for disturbances / MVs
        self._u_idx = dict(
            spumpstarg=0,
            valvextarg=[1, 2, 3],
            Irad=1 + self.n_lines,
            Tamb=2 + self.n_lines,
            Tin=3 + self.n_lines,
        )

        # Axial positions along the collector
        self.z = np.linspace(0, cfg.L, self.N)

        # Flow-marker particles (Lagrangian tracers on spatial plots)
        self._n_markers = 10
        self._pipe_area = np.pi * cfg.R**2
        # Stagger each line's particles by 1/n_lines of the inter-marker gap
        # so markers from different lines don't all start at the same z.
        spacing = cfg.L / self._n_markers
        self._z_particles = np.array(
            [
                (np.arange(self._n_markers) + i / self.n_lines)
                * spacing
                % cfg.L
                for i in range(self.n_lines)
            ]
        )

        # Rolling history buffers
        def _buf():
            return collections.deque(maxlen=history_len)

        self._t_buf = _buf()
        self._Texit_buf = _buf()
        self._mdot_buf = _buf()
        self._spumps_buf = _buf()
        self._spumptarg_buf = _buf()
        self._valvex_buf = _buf()
        self._irad_buf = _buf()
        self._tin_buf = _buf()

        # Matplotlib objects populated by _build_figure
        self._fig = None
        self._ax_profile = None
        self._anim = None
        self._sliders = {}
        self._tb_lines = []
        self._pt_lines = []
        self._tb_particle_markers = []
        self._Texit_lines = []
        self._mdot_lines = []
        self._pump_act_line = None
        self._pump_targ_line = None
        self._valve_lines = []
        self._irad_line = None
        self._tin_ts_line = None
        self._ts_axes = []
        self._btn = None
        self._ff_btn = None
        self._ff_steps = 0  # pending fast-forward steps to drain on next frame
        self._running = True
        self._time_text = None
        self._y_min_last = (
            None  # cached y-axis lower bound for temperature plots
        )

    # ── State accessors ────────────────────────────────────────────────────

    def _tb_profile(self, line: int) -> np.ndarray:
        """Fluid temperature profile for one line (N points)."""
        return self.x[
            self._tb_off + line : self._tb_off
            + self.n_lines * self.N : self.n_lines
        ]

    def _pt_profile(self, line: int) -> np.ndarray:
        """Pipe wall temperature profile for one line (N points)."""
        return self.x[
            self._pt_off + line : self._pt_off
            + self.n_lines * self.N : self.n_lines
        ]

    # ── Particle tracking ──────────────────────────────────────────────────

    def _advance_particles(self):
        """Move Lagrangian tracer particles by one display frame."""
        dt = self._dt * self.steps_per_frame
        L = self.plant.config.L
        mdot_off = 1 + self.n_lines  # state index of Mdot[0]
        for i in range(self.n_lines):
            tb = np.array(self._tb_profile(i))
            mdot = float(self.x[mdot_off + i])
            v_profile = mdot / (_rho(tb) * self._pipe_area)
            v_at_p = np.interp(self._z_particles[i], self.z, v_profile)
            self._z_particles[i] = (self._z_particles[i] + v_at_p * dt) % L

    # ── Simulation ─────────────────────────────────────────────────────────

    def _step(self):
        self.x = np.asarray(self.plant.F(self.t, self.x, self.u)).ravel()
        self.t += self._dt

    def _record(self):
        y = np.asarray(self.plant.H(self.t, self.x, self.u)).ravel()
        self._t_buf.append(self.t)
        self._Texit_buf.append([float(y[i]) for i in self._T_exit_idx])
        self._mdot_buf.append([float(y[i]) for i in range(self.n_lines)])
        self._spumps_buf.append(float(self.x[0]))
        self._spumptarg_buf.append(float(self.u[0]))
        self._valvex_buf.append(
            [float(self.x[1 + i]) for i in range(self.n_lines)]
        )
        self._irad_buf.append(float(self.u[self._u_idx["Irad"]]))
        self._tin_buf.append(float(self.u[self._u_idx["Tin"]]))

    # ── Figure construction ────────────────────────────────────────────────

    def _build_figure(self) -> plt.Figure:
        fig = plt.figure(figsize=(16, 8))
        try:
            fig.canvas.manager.set_window_title(
                "Solar Collector — Live Simulation"
            )
        except AttributeError:
            pass

        slider_zone = 0.20  # fraction of figure height reserved for sliders

        gs = mgridspec.GridSpec(
            2,
            4,
            figure=fig,
            top=0.960,
            bottom=slider_zone + 0.06,
            hspace=0.35,
            wspace=0.40,
            height_ratios=[1.8, 1.0],
        )

        ax_profile = fig.add_subplot(gs[0, 0:2])  # combined temp profiles
        ax_Texit = fig.add_subplot(gs[0, 2:4])  # exit / inlet temperatures
        ax_irad = fig.add_subplot(gs[1, 0])
        ax_pump = fig.add_subplot(gs[1, 1])
        ax_valve = fig.add_subplot(gs[1, 2])
        ax_mdot = fig.add_subplot(gs[1, 3])

        self._ax_profile = ax_profile
        self._ts_axes = [ax_Texit, ax_irad, ax_pump, ax_valve, ax_mdot]
        cfg = self.plant.config

        # Compute initial shared y-range for both temperature plots
        all_init_t = [np.min(self._tb_profile(i)) for i in range(self.n_lines)]
        all_init_t += [
            np.min(self._pt_profile(i)) for i in range(self.n_lines)
        ]
        init_ymin = min(all_init_t) - 5

        # ── Spatial: fluid (solid) + pipe wall (dashed) temperatures ─────
        ax_profile.set(
            xlim=(0, cfg.L),
            ylim=(init_ymin, _T_PLOT_MAX),
            xlabel="Position (m)",
            ylabel="Temperature (°C)",
            title="Temperature profiles — solid: fluid,  dashed: pipe wall",
        )
        ax_profile.grid(True, alpha=0.3)
        self._tb_lines = [
            ax_profile.plot(
                self.z,
                self._tb_profile(i),
                color=_COLORS[i],
                lw=1.5,
                label=_LINE_LABELS[i],
            )[0]
            for i in range(self.n_lines)
        ]
        self._pt_lines = [
            ax_profile.plot(
                self.z,
                self._pt_profile(i),
                color=_COLORS[i],
                lw=1.0,
                ls="--",
            )[0]
            for i in range(self.n_lines)
        ]
        ax_profile.axhline(
            _T_SP, color="tab:red", ls="--", lw=1.0, zorder=2, label="T_SP"
        )
        ax_profile.axhline(
            _T_MAX, color="#444444", ls="--", lw=1.0, zorder=2, label="T max"
        )
        ax_profile.legend(loc="upper left", fontsize=8)
        self._tb_particle_markers = [
            ax_profile.plot(
                [], [], "|", color=_COLORS[i], ms=7, mew=1.0, zorder=5
            )[0]
            for i in range(self.n_lines)
        ]

        # ── Time series: exit / inlet fluid temperatures ──────────────────
        ax_Texit.set(
            ylim=(init_ymin, _T_PLOT_MAX),
            xlabel="Time (s)",
            ylabel="Temperature (°C)",
            title="Fluid inlet and exit temperatures",
        )
        ax_Texit.axhline(
            _T_SP, color="tab:red", ls="--", lw=1.0, zorder=2, label="T_SP"
        )
        ax_Texit.axhline(
            _T_MAX, color="#444444", ls="--", lw=1.0, zorder=2, label="T max"
        )
        ax_Texit.grid(True, alpha=0.3)
        self._Texit_lines = [
            ax_Texit.plot(
                [], [], color=_COLORS[i], lw=1.2, label=_LINE_LABELS[i]
            )[0]
            for i in range(self.n_lines)
        ]
        (self._tin_ts_line,) = ax_Texit.plot(
            [], [], color="gray", lw=1.2, ls="--", label="Tin"
        )
        ax_Texit.legend(loc="upper left", fontsize=7)

        # ── Time series: solar irradiance ─────────────────────────────────
        ax_irad.set(
            ylim=(-0.05, 1.4),
            xlabel="Time (s)",
            ylabel="kW/m²",
            title="Solar irradiance",
        )
        ax_irad.grid(True, alpha=0.3)
        (self._irad_line,) = ax_irad.plot([], [], color="goldenrod", lw=1.5)

        # ── Time series: valve positions ──────────────────────────────────
        ax_valve.set(
            ylim=(0, 1.05),
            xlabel="Time (s)",
            ylabel="Position",
            title="Valve positions",
        )
        ax_valve.grid(True, alpha=0.3)
        self._valve_lines = [
            ax_valve.plot(
                [], [], color=_COLORS[i], lw=1.2, label=_LINE_LABELS[i]
            )[0]
            for i in range(self.n_lines)
        ]
        ax_valve.legend(loc="upper left", fontsize=7)

        # ── Time series: pump speed ───────────────────────────────────────
        ax_pump.set(
            ylim=(_PUMP_MIN - 0.05, 1.05),
            xlabel="Time (s)",
            ylabel="Speed",
            title="Pump speed",
        )
        ax_pump.grid(True, alpha=0.3)
        (self._pump_targ_line,) = ax_pump.plot(
            [], [], "k--", lw=1.2, label="target"
        )
        (self._pump_act_line,) = ax_pump.plot(
            [], [], color="tab:red", lw=1.2, label="actual"
        )
        ax_pump.legend(loc="upper left", fontsize=7)

        # ── Time series: mass flow rates ──────────────────────────────────
        ax_mdot.set(
            ylim=(0, 5),
            xlabel="Time (s)",
            ylabel="Mdot (kg/s)",
            title="Line flow rates",
        )
        ax_mdot.grid(True, alpha=0.3)
        self._mdot_lines = [
            ax_mdot.plot(
                [], [], color=_COLORS[i], lw=1.2, label=_LINE_LABELS[i]
            )[0]
            for i in range(self.n_lines)
        ]
        ax_mdot.legend(loc="upper left", fontsize=7)

        # ── Sliders ───────────────────────────────────────────────────────
        self._build_sliders(fig)

        self._fig = fig
        return fig

    def _build_sliders(self, fig: plt.Figure):
        """Add sliders in two columns in the reserved bottom area.

        Left column  (col 0): Irad, Tamb, Tin  (rows 3→1, row 0 empty)
        Right column (col 1): Pump target, Valve 1, Valve 2, Valve 3  (rows 3→0)

        Valve sliders are coloured to match the per-line colours used in plots.
        """
        sl_h = 0.025
        row_gap = 0.040  # tight vertical pitch between rows
        col0_left, col1_left = 0.15, 0.58
        col_w = 0.28

        # row_bottom[r] = figure y-coordinate of slider bottom for row r
        row_bottom = {r: 0.01 + r * row_gap for r in range(4)}

        # (key, label, vmin, vmax, u_index, row, col, color, nominal)
        # nominal: position of the red reference marker; None → use actual init
        specs = [
            (
                "Irad",
                "Irad (kW/m²)",
                0.0,
                1.2,
                self._u_idx["Irad"],
                3,
                0,
                None,
                0.95,
            ),
            (
                "Tamb",
                "Tamb (°C)",
                10.0,
                50.0,
                self._u_idx["Tamb"],
                2,
                0,
                None,
                None,
            ),
            (
                "Tin",
                "Tin (°C)",
                10.0,
                400.0,
                self._u_idx["Tin"],
                1,
                0,
                None,
                None,
            ),
            (
                "spump",
                "Pump target",
                _PUMP_MIN,
                _PUMP_MAX,
                0,
                3,
                1,
                None,
                None,
            ),
            (
                "v1",
                "Valve 1",
                _VALVE_MIN,
                _VALVE_MAX,
                1,
                2,
                1,
                _COLORS[0],
                None,
            ),
            (
                "v2",
                "Valve 2",
                _VALVE_MIN,
                _VALVE_MAX,
                2,
                1,
                1,
                _COLORS[1],
                None,
            ),
            (
                "v3",
                "Valve 3",
                _VALVE_MIN,
                _VALVE_MAX,
                3,
                0,
                1,
                _COLORS[2],
                None,
            ),
        ]

        self._sliders = {}
        for key, label, vmin, vmax, u_idx, row, col, color, nominal in specs:
            left_x = col0_left if col == 0 else col1_left
            ax = fig.add_axes([left_x, row_bottom[row], col_w, sl_h])
            actual_init = float(self.u[u_idx])
            valinit = nominal if nominal is not None else actual_init
            kwargs = {"valinit": valinit}
            if color is not None:
                kwargs["color"] = color
            sl = mwidgets.Slider(ax, label, vmin, vmax, **kwargs)
            if color is not None:
                sl.label.set_color(color)
                sl.label.set_fontweight("bold")
            # If nominal differs from actual init, move slider to actual position
            # while restoring the red reference marker to the nominal position.
            if nominal is not None and actual_init != valinit:
                sl.set_val(actual_init)
                sl.vline.set_xdata([valinit, valinit])
                sl.valinit = valinit

            def _cb(val, idx=u_idx):
                self.u[idx] = val

            sl.on_changed(_cb)
            self._sliders[key] = sl

        # Time counter + Start/Stop + fast-forward buttons in row-0, left-column slot
        btn_w = 0.09
        btn_gap = 0.01
        btn_x = col0_left + col_w - btn_w  # STOP/START (rightmost)
        ff_btn_x = btn_x - btn_w - btn_gap  # +15s (just to the left)
        time_y = row_bottom[0] + sl_h / 2
        self._time_text = fig.text(
            col0_left,
            time_y,
            "t =    0.0 s",
            va="center",
            ha="left",
            fontsize=9,
            fontweight="bold",
            fontfamily="monospace",
        )
        ax_btn = fig.add_axes([btn_x, row_bottom[0], btn_w, sl_h])
        self._btn = mwidgets.Button(ax_btn, "STOP")
        self._btn.label.set_fontweight("bold")

        def _toggle(_event):
            if self._running:
                self._anim.pause()
                self._btn.label.set_text("START")
            else:
                self._anim.resume()
                self._btn.label.set_text("STOP")
            self._running = not self._running
            fig.canvas.draw_idle()

        self._btn.on_clicked(_toggle)

        ax_ff_btn = fig.add_axes([ff_btn_x, row_bottom[0], btn_w, sl_h])
        self._ff_btn = mwidgets.Button(ax_ff_btn, "+15 s")

        def _fast_forward(_event):
            self._ff_steps = round(15.0 / self._dt)

        self._ff_btn.on_clicked(_fast_forward)

    # ── Animation callbacks ────────────────────────────────────────────────

    def _all_ts_lines(self):
        return (
            self._Texit_lines
            + [self._tin_ts_line]
            + self._mdot_lines
            + [self._pump_targ_line, self._pump_act_line, self._irad_line]
            + self._valve_lines
        )

    def _all_artists(self):
        return (
            self._tb_lines
            + self._tb_particle_markers
            + self._pt_lines
            + self._all_ts_lines()
        )

    def _init_anim(self):
        for line in self._all_ts_lines():
            line.set_data([], [])
        return self._all_artists()

    def _update_temp_ylim(self, data_min: float):
        """Update the shared y-axis of both temperature plots only when needed."""
        y_min = data_min - 5
        if self._y_min_last is None or abs(y_min - self._y_min_last) > 2.0:
            self._ax_profile.set_ylim(y_min, _T_PLOT_MAX)
            self._ts_axes[0].set_ylim(y_min, _T_PLOT_MAX)
            self._y_min_last = y_min

    def _update(self, _frame):
        for _ in range(self.steps_per_frame):
            self._step()
        self._record()
        if self._ff_steps > 0:
            for _ in range(self._ff_steps):
                self._step()
                self._record()
            self._ff_steps = 0
        self._time_text.set_text(f"t = {self.t:6.1f} s")

        # Spatial profiles — copy avoids stale-view issue when self.x is replaced
        self._advance_particles()
        t_data_mins = []
        for i in range(self.n_lines):
            tb = np.array(self._tb_profile(i))
            pt = np.array(self._pt_profile(i))
            self._tb_lines[i].set_data(self.z, tb)
            self._pt_lines[i].set_data(self.z, pt)
            zp = self._z_particles[i]
            self._tb_particle_markers[i].set_data(
                zp, np.interp(zp, self.z, tb)
            )
            t_data_mins.append(float(tb.min()))
            t_data_mins.append(float(pt.min()))

        if len(self._t_buf) < 2:
            self._update_temp_ylim(min(t_data_mins))
            return self._all_artists()

        t_arr = np.array(self._t_buf)
        t1 = float(t_arr[-1])
        t0_plot = max(float(t_arr[0]), t1 - self.plot_horizon)
        for ax in self._ts_axes:
            ax.set_xlim(t0_plot, t0_plot + self.plot_horizon)

        T_exit_arr = np.array(self._Texit_buf)
        mdot_arr = np.array(self._mdot_buf)
        valvex_arr = np.array(self._valvex_buf)
        spumps_arr = np.array(self._spumps_buf)
        sptarg_arr = np.array(self._spumptarg_buf)
        irad_arr = np.array(self._irad_buf)

        tin_arr = np.array(self._tin_buf)

        for i in range(self.n_lines):
            self._Texit_lines[i].set_data(t_arr, T_exit_arr[:, i])
            self._mdot_lines[i].set_data(t_arr, mdot_arr[:, i])
            self._valve_lines[i].set_data(t_arr, valvex_arr[:, i])

        self._tin_ts_line.set_data(t_arr, tin_arr)
        self._pump_act_line.set_data(t_arr, spumps_arr)
        self._pump_targ_line.set_data(t_arr, sptarg_arr)
        self._irad_line.set_data(t_arr, irad_arr)

        # Shared y-range for both temperature plots: auto min, fixed max 450
        t_data_mins.append(float(T_exit_arr.min()))
        t_data_mins.append(float(tin_arr.min()))
        self._update_temp_ylim(min(t_data_mins))

        return self._all_artists()

    # ── Public entry point ─────────────────────────────────────────────────

    def run(self):
        """Build the figure, start the animation loop, and show the window."""
        self._build_figure()
        self._record()  # populate buffers with t=0 state before first frame
        self._anim = FuncAnimation(
            self._fig,
            self._update,
            init_func=self._init_anim,
            interval=self.frame_interval_ms,
            blit=False,
            cache_frame_data=False,
            repeat=False,
            frames=None,  # infinite
        )
        plt.show()
