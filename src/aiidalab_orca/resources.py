"""Resource controls with explicit display units and stable backend values."""

import html
import math

import ipywidgets as ipw
import traitlets as tl


def memory_label(memory_mb):
    """Format an existing integer MiB budget without changing its meaning."""
    return f"{memory_mb / 1024:g} GiB"


def execution_hint(context):
    """Keep execution location and scheduler claims tied to selected metadata."""
    if context is None:
        execution = "Select an available ORCA code to identify its execution computer."
    else:
        computer, transport, scheduler = (html.escape(context[key])
                                          for key in ("computer", "transport", "scheduler"))
        execution = (f"Runs on <b>{computer}</b> using <code>{transport}</code> transport "
                     f"and the <code>{scheduler}</code> scheduler.")
        if context["scheduler"] == "core.direct":
            execution += " The direct scheduler does not enforce a hard memory limit."
    return (f"<p>{execution}</p><p>ORCA uses 75% of the total memory budget divided "
            "by the process count.</p>")


class _GiBInput(ipw.BoundedFloatText):
    @tl.validate("value")
    def _validate_value(self, proposal):
        value = proposal["value"]
        if not math.isfinite(value):
            raise tl.TraitError("Memory must be a finite number of GiB.")
        return min(self.max, max(self.min, value))


class MemoryInput(ipw.VBox):
    """Display GiB while keeping ``value`` in integer MiB for saved settings."""

    value = tl.Int()

    def __init__(self, *, value=2048, min=256, max=1048576, style=None, layout=None):
        self._minimum, self._maximum = min, max
        self._syncing = False
        self.gib = _GiBInput(
            value=value / 1024, min=min / 1024, max=max / 1024, step=.25,
            description="Total memory (GiB)", style=style or {},
            layout=layout or ipw.Layout(),
            tooltip="1 GiB = 1024 MiB. Saved settings and backend budgets use integer MiB.",
        )
        super().__init__([self.gib])
        self.value = value
        self.gib.observe(self._from_display, names="value")

    @tl.validate("value")
    def _validate_value(self, proposal):
        return min(self._maximum, max(self._minimum, proposal["value"]))

    @tl.observe("value")
    def _from_backend(self, _):
        if not self._syncing and hasattr(self, "gib"):
            self.gib.value = self.value / 1024

    def _from_display(self, _):
        self._syncing = True
        try:
            self.value = round(self.gib.value * 1024)
        finally:
            self._syncing = False
