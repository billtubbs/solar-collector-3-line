"""Live animated simulation of the 3-line parabolic solar collector.

Displays two spatial profile plots (fluid and pipe-wall temperatures vs
axial position) and five scrolling time-series plots, with sliders to
adjust manipulated variables and disturbance inputs in real time.

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

_COLORS = ["tab:blue", "tab:orange", "tab:green"]
_LINE_LABELS = ["Line 1", "Line 2", "Line 3"]


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
        self._anim = None
        self._sliders = {}
        self._tb_lines = []
        self._pt_lines = []
        self._Texit_lines = []
        self._mdot_lines = []
        self._pump_act_line = None
        self._pump_targ_line = None
        self._valve_lines = []
        self._irad_line = None
        self._tin_ts_line = None
        self._ts_axes = []
        self._btn = None
        self._running = True
        self._time_text = None

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
        fig = plt.figure(figsize=(12, 11))
        try:
            fig.canvas.manager.set_window_title(
                "Solar Collector — Live Simulation"
            )
        except AttributeError:
            pass

        slider_zone = 0.20  # fraction of figure height reserved for sliders

        gs = mgridspec.GridSpec(
            4,
            3,
            figure=fig,
            top=0.965,
            bottom=slider_zone + 0.02,
            hspace=0.65,
            wspace=0.38,
        )

        ax_tb = fig.add_subplot(gs[0, :])  # fluid temperature profiles
        ax_pt = fig.add_subplot(gs[1, :])  # pipe wall temperature profiles
        ax_Texit = fig.add_subplot(gs[2, 0])
        ax_mdot = fig.add_subplot(gs[2, 1])
        ax_pump = fig.add_subplot(gs[2, 2])
        ax_irad = fig.add_subplot(gs[3, 0])
        ax_valve = fig.add_subplot(gs[3, 1:])

        self._ts_axes = [ax_Texit, ax_mdot, ax_pump, ax_irad, ax_valve]
        cfg = self.plant.config

        # ── Spatial: fluid temperatures ───────────────────────────────────
        ax_tb.set(
            xlim=(0, cfg.L),
            ylim=(270, 450),
            xlabel="Position (m)",
            ylabel="T_fluid (°C)",
            title="Fluid temperature profiles",
        )
        ax_tb.grid(True, alpha=0.3)
        self._tb_lines = [
            ax_tb.plot(
                self.z,
                self._tb_profile(i),
                color=_COLORS[i],
                lw=1.5,
                label=_LINE_LABELS[i],
            )[0]
            for i in range(self.n_lines)
        ]
        ax_tb.legend(loc="upper left", fontsize=8)

        # ── Spatial: pipe wall temperatures ───────────────────────────────
        ax_pt.set(
            xlim=(0, cfg.L),
            ylim=(270, 500),
            xlabel="Position (m)",
            ylabel="T_pipe (°C)",
            title="Pipe wall temperature profiles",
        )
        ax_pt.grid(True, alpha=0.3)
        self._pt_lines = [
            ax_pt.plot(
                self.z,
                self._pt_profile(i),
                color=_COLORS[i],
                lw=1.5,
                label=_LINE_LABELS[i],
            )[0]
            for i in range(self.n_lines)
        ]
        ax_pt.legend(loc="upper left", fontsize=8)

        # ── Time series: exit fluid temperatures ──────────────────────────
        ax_Texit.set(
            ylim=(270, 450),
            xlabel="Time (s)",
            ylabel="T_exit (°C)",
            title="Exit fluid temperatures",
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

        # ── Time series: mass flow rates ──────────────────────────────────
        ax_mdot.set(
            ylim=(0, 5),
            xlabel="Time (s)",
            ylabel="Mdot (kg/s)",
            title="Mass flow rates",
        )
        ax_mdot.grid(True, alpha=0.3)
        self._mdot_lines = [
            ax_mdot.plot(
                [], [], color=_COLORS[i], lw=1.2, label=_LINE_LABELS[i]
            )[0]
            for i in range(self.n_lines)
        ]
        ax_mdot.legend(loc="upper left", fontsize=7)

        # ── Time series: pump speed ───────────────────────────────────────
        ax_pump.set(
            ylim=(0, 1.05),
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

        # ── Time series: solar irradiance ─────────────────────────────────
        ax_irad.set(
            ylim=(0, 1.4),
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

        # ── Sliders ───────────────────────────────────────────────────────
        self._build_sliders(fig, slider_zone)

        self._fig = fig
        return fig

    def _build_sliders(self, fig: plt.Figure, slider_zone: float):
        """Add sliders in two columns in the reserved bottom area.

        Left column  (col 0): Irad, Tamb, Tin  (rows 3→1, row 0 empty)
        Right column (col 1): Pump target, Valve 1, Valve 2, Valve 3  (rows 3→0)
        """
        sl_h = 0.025
        row_gap = 0.040  # tight vertical pitch between rows
        col0_left, col1_left = 0.15, 0.58
        col_w = 0.28

        # row_bottom[r] = figure y-coordinate of slider bottom for row r
        row_bottom = {r: 0.01 + r * row_gap for r in range(4)}

        # (key, label, vmin, vmax, u_index, row, col)
        specs = [
            ("Irad", "Irad (kW/m²)", 0.0, 1.2, self._u_idx["Irad"], 3, 0),
            ("Tamb", "Tamb (°C)", 0.0, 50.0, self._u_idx["Tamb"], 2, 0),
            ("Tin", "Tin (°C)", 200.0, 400.0, self._u_idx["Tin"], 1, 0),
            ("spump", "Pump target", 0.1, 1.0, 0, 3, 1),
            ("v1", "Valve 1", 0.1, 1.0, 1, 2, 1),
            ("v2", "Valve 2", 0.1, 1.0, 2, 1, 1),
            ("v3", "Valve 3", 0.1, 1.0, 3, 0, 1),
        ]

        self._sliders = {}
        for key, label, vmin, vmax, u_idx, row, col in specs:
            left_x = col0_left if col == 0 else col1_left
            ax = fig.add_axes([left_x, row_bottom[row], col_w, sl_h])
            sl = mwidgets.Slider(
                ax, label, vmin, vmax, valinit=float(self.u[u_idx])
            )

            def _cb(val, idx=u_idx):
                self.u[idx] = val

            sl.on_changed(_cb)
            self._sliders[key] = sl

        # Time counter + Start/Stop button in the empty row-0, left-column slot
        btn_w = 0.09
        btn_x = col0_left + col_w - btn_w
        time_y = row_bottom[0] + sl_h / 2
        self._time_text = fig.text(
            col0_left, time_y, "t =    0.0 s",
            va="center", ha="left", fontsize=9,
            fontweight="bold", fontfamily="monospace",
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
        return self._tb_lines + self._pt_lines + self._all_ts_lines()

    def _init_anim(self):
        for line in self._all_ts_lines():
            line.set_data([], [])
        return self._all_artists()

    def _update(self, _frame):
        for _ in range(self.steps_per_frame):
            self._step()
        self._record()
        self._time_text.set_text(f"t = {self.t:6.1f} s")

        # Spatial profiles — copy avoids stale-view issue when self.x is replaced
        for i in range(self.n_lines):
            self._tb_lines[i].set_data(self.z, np.array(self._tb_profile(i)))
            self._pt_lines[i].set_data(self.z, np.array(self._pt_profile(i)))

        if len(self._t_buf) < 2:
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
