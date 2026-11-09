"""Large-artifact retention and an independent native-text retrieval threshold."""

import ipywidgets as ipw
import traitlets as tl

from aiida_empa_orca.native_logs import DEFAULT_MAXSIZEOUTPUT, output_policy


def description(policy):
    policy = output_policy(policy)
    destination = ('Leave on the calculation computer' if policy['mode'] == 'remote' else
                   'Stash on the calculation computer: ' + policy['stash_directory'])
    maximum = policy.get('maxsizeoutput', DEFAULT_MAXSIZEOUTPUT) / 1024**2
    return (destination + f'. Native text outputs up to {maximum:g} MiB are retrieved unchanged; '
            'larger outputs use an explicit notice and a separate validation extract')


class FullFileRetention(ipw.VBox):
    revision = tl.Int()

    def __init__(self, *, directory=''):
        self.mode = ipw.Dropdown(description='Full files',
            options=[('Leave on the calculation computer', 'remote'),
                     ('Stash on the calculation computer', 'stash')],
            layout=ipw.Layout(width='95%'), style={'description_width': 'initial'})
        self.directory = ipw.Text(value=directory, description='Stash directory',
            layout=ipw.Layout(width='95%'), style={'description_width': 'initial'})
        self.maxsizeoutput = ipw.BoundedFloatText(value=DEFAULT_MAXSIZEOUTPUT / 1024**2,
            min=0, max=1024**2, step=1, description='maxsizeoutput (MiB)',
            style={'description_width': 'initial'}, layout=ipw.Layout(width='300px'))
        output_options = ipw.Accordion(children=[ipw.VBox([self.maxsizeoutput, ipw.HTML(
            '<p>Original output files up to this size are retrieved in full. Above the threshold, '
            'a separate validation extract and an explicit outputcat notice are stored. '
            '0 always selects the extract. This does not truncate scientific result arrays.</p>')])],
            selected_index=None)
        output_options.set_title(0, 'Output retrieval')
        super().__init__([self.mode, self.directory, output_options, ipw.HTML(
            '<p>Wavefunctions, integrals and full cubes remain remote or are stashed. '
            'The output-file threshold is independent of their size. Remote files depend '
            'on the calculation computer\'s cleanup policy.</p>')])
        for field in (self.mode, self.directory, self.maxsizeoutput):
            field.observe(self._changed, names='value')
        self._changed()

    def _changed(self, _=None):
        self.directory.layout.display = '' if self.mode.value == 'stash' else 'none'
        self.revision += 1

    def values(self):
        return output_policy({'mode': self.mode.value, 'stash_directory': self.directory.value.strip(),
                              'maxsizeoutput': round(self.maxsizeoutput.value * 1024**2)})

    def close(self):
        if getattr(self, '_closed', False):
            return
        self._closed = True
        for field in (self.mode, self.directory, self.maxsizeoutput):
            field.unobserve(self._changed, names='value')
        super().close()
