"""Small presentation helpers shared by independent property panels."""

import html

import ipywidgets as ipw


class ComputePanel(ipw.VBox):
    """Keep optional calculation inputs behind an explicit action."""

    def __init__(self, title, children):
        self.toggle = ipw.ToggleButton(description=title, icon='plus',
            layout=ipw.Layout(width='auto'), tooltip='Show or hide settings')
        self.body = ipw.VBox(children, layout=ipw.Layout(display='none'))
        self.toggle.observe(self._changed, names='value')
        super().__init__([self.toggle, self.body])
        self.add_class('orca-compute-panel')

    def _changed(self, change):
        self.body.layout.display = '' if change['new'] else 'none'
        self.toggle.icon = 'minus' if change['new'] else 'plus'

    def show(self):
        self.toggle.value = True


class LazyTabs(ipw.Tab):
    """Construct a property once, retaining its viewers and selections."""

    def __init__(self, sections):
        self.section_keys = [key for key, _, _ in sections]
        self.factories = {key: factory for key, _, factory in sections}
        self.panels = {}
        super().__init__(children=[ipw.VBox() for _ in sections], selected_index=0,
                         layout=ipw.Layout(width='100%'))
        for index, (_, title, _) in enumerate(sections):
            self.set_title(index, title)
        self.observe(self._changed, names='selected_index')
        self._load(0)

    def _load(self, index):
        key = self.section_keys[index]
        if key not in self.panels:
            try:
                panel = self.factories[key]()
            except Exception as exc:
                retry = ipw.Button(description='Retry opening this section', icon='refresh',
                                   layout=ipw.Layout(width='auto'))
                retry.on_click(lambda _: self._load(index))
                panel = ipw.VBox([ipw.HTML('<p class="orca-notice">'+html.escape(str(exc))+'</p>'), retry])
            else:
                self.panels[key] = panel
            old = self.children[index]
            children = list(self.children)
            children[index] = panel
            self.children = children
            old.close()
        panel = self.panels.get(key)
        if panel and hasattr(panel, 'set_active'):
            panel.set_active(True)
        return panel

    def _changed(self, change):
        old = change['old']
        if old is not None:
            panel = self.panels.get(self.section_keys[old])
            if panel and hasattr(panel, 'set_active'):
                panel.set_active(False)
        if change['new'] is not None:
            self._load(change['new'])

    def show_section(self, key):
        index = self.section_keys.index(key)
        self.selected_index = index
        return self._load(index)

    def set_active(self, active):
        if self.selected_index is not None:
            panel = self.panels.get(self.section_keys[self.selected_index])
            if panel and hasattr(panel, 'set_active'):
                panel.set_active(active)
