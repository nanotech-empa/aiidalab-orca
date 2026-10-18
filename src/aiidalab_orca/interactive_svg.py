"""Small ipywidgets-compatible SVG event bridge, without external JavaScript."""
from pathlib import Path

import anywidget
import traitlets as tl


class InteractiveSvg(anywidget.AnyWidget):
    _esm = Path(__file__).parent / 'static' / 'interactive_svg.js'
    value = tl.Unicode('').tag(sync=True)

    def __init__(self, on_action=None, **kwargs):
        self.on_action = on_action
        super().__init__(**kwargs)
        self.on_msg(self._receive)

    def _receive(self, _, content, buffers):
        if self.on_action and isinstance(content, dict):
            self.on_action(content)

    def close(self):
        self.on_action = None
        self.on_msg(self._receive, remove=True)
        super().close()
