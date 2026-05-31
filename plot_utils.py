"""Utility functions for time-series and input-output plots."""

import matplotlib.pyplot as plt


def make_tsplots(
    t,
    plot_data,
    t_label="Time",
    sharex=True,
    sharey=False,
    subplot_height=2.0,
    figsize=None,
):
    n = len(plot_data)
    if figsize is None:
        figsize = (7, 0.5 + subplot_height * n)
    fig, axes = plt.subplots(
        n, 1, sharex=sharex, sharey=sharey, figsize=figsize
    )
    axes = [axes] if isinstance(axes, plt.Axes) else axes
    for ax, (title, data) in zip(axes, plot_data.items()):
        kind = data.get("kind", "plot")
        y_label = data.get("y_label", None)
        kwargs = data.get("kwargs", {})
        if kind == "plot":
            ax.plot(t, data["y"], **kwargs)
        elif kind == "step":
            ax.step(t, data["y"], **kwargs)
        else:
            raise ValueError("invalid plot type")
        ax.set_ylabel(y_label)
        ax.grid()
        ax.legend(data["labels"])
        ax.set_title(title)
    axes[-1].set_xlabel(t_label)
    return fig, axes


def make_ioplots(
    t,
    inputs=None,
    states=None,
    outputs=None,
    inputs_labels=None,
    states_labels=None,
    outputs_labels=None,
    t_label="Time",
    figsize=None,
):
    plot_data = {}
    if outputs is not None:
        plot_data["Outputs"] = {"y": outputs, "labels": outputs_labels}
    if states is not None:
        plot_data["States"] = {"y": states, "labels": states_labels}
    if inputs is not None:
        plot_data["Inputs"] = {
            "y": inputs,
            "labels": inputs_labels,
            "kind": "step",
            "kwargs": {"where": "post"},
        }
    return make_tsplots(t, plot_data, figsize=figsize, t_label=t_label)
