"""Explicit full-file retention controls; never offer retrieval of large data."""

import ipywidgets as ipw
import traitlets as tl

from aiida_empa_orca.native_logs import output_policy


def description(policy):
    policy = output_policy(policy)
    return ('Leave on the calculation computer' if policy['mode'] == 'remote' else
            'Stash on the calculation computer: ' + policy['stash_directory'])


class FullFileRetention(ipw.VBox):
    revision = tl.Int()

    def __init__(self, *, directory=''):
        self.mode = ipw.Dropdown(description='Full files',
            options=[('Leave on the calculation computer', 'remote'),
                     ('Stash on the calculation computer', 'stash')],
            layout=ipw.Layout(width='95%'), style={'description_width': 'initial'})
        self.directory = ipw.Text(value=directory, description='Stash directory',
            layout=ipw.Layout(width='95%'), style={'description_width': 'initial'})
        super().__init__([self.mode, self.directory, ipw.HTML(
            '<p>Full native logs and wavefunctions remain remote or are stashed. '
            'Only compact results and diagnostics are retrieved. Remote files depend '
            'on the calculation computer\'s cleanup policy.</p>')])
        for field in (self.mode, self.directory):
            field.observe(self._changed, names='value')
        self._changed()

    def _changed(self, _=None):
        self.directory.layout.display = '' if self.mode.value == 'stash' else 'none'
        self.revision += 1

    def values(self):
        return output_policy({'mode': self.mode.value, 'stash_directory': self.directory.value.strip()})

    def close(self):
        if getattr(self, '_closed', False):
            return
        self._closed = True
        for field in (self.mode, self.directory):
            field.unobserve(self._changed, names='value')
        super().close()
