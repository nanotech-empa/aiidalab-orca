"""Small presentation helpers shared by independent property panels."""

import html

import ipywidgets as ipw


def data_table(headers, rows, *, numeric_columns=(), label='Calculation details'):
    """Readable, scoped HTML tables that do not depend on notebook theme CSS."""
    numeric_columns = set(numeric_columns)
    def cell(value, index, *, heading=False):
        tag = 'th' if heading else 'td'
        alignment = 'right' if index in numeric_columns else 'left'
        style = (f'padding:10px 14px;text-align:{alignment};vertical-align:top;'
                 'border-bottom:1px solid var(--jp-border-color2,#d8dee6);'
                 'line-height:1.45;overflow-wrap:break-word;')
        if heading:
            style += 'font-weight:600;'
        elif index in numeric_columns:
            style += 'font-variant-numeric:tabular-nums;white-space:nowrap;'
        scope = ' scope="col"' if heading else ''
        return f'<{tag}{scope} style="{style}">{html.escape(str(value))}</{tag}>'
    head = '<tr>'+''.join(cell(value,index,heading=True) for index,value in enumerate(headers))+'</tr>'
    body = ''.join('<tr>'+''.join(cell(value,index) for index,value in enumerate(row))+'</tr>' for row in rows)
    return ('<div style="max-width:100%;overflow-x:auto;">'
            f'<table aria-label="{html.escape(label)}" style="width:100%;border-collapse:collapse;'
            'border-spacing:0;font-size:inherit;margin:12px 0;">'
            '<thead>'+head+'</thead><tbody>'+body+'</tbody></table></div>')


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


class _LazySections:
    """Construct each section once, retaining its viewers and selections."""

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


class LazyTabs(_LazySections, ipw.Tab):
    """Lazy sections with their own tab navigation."""


class LazyStack(_LazySections, ipw.Stack):
    """Lazy sections controlled by an external selector, without a second menu."""
