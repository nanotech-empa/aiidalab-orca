"""Small adapters for the shared AiiDAlab wizard; no AiiDA nodes are retained."""

import ipywidgets as ipw
from aiidalab_widgets_base import WizardAppWidgetStep


class GeometryStep(ipw.VBox, WizardAppWidgetStep):
    """Show a step's controls only when its prerequisites are confirmed."""

    def __init__(self, content, message):
        self.content = ipw.VBox(content)
        self.blocker = ipw.HTML(f"<p>{message}</p>")
        super().__init__(children=[self.blocker])

    def update(self, state, available):
        self.children = [self.content if available else self.blocker]
        self.state = state
