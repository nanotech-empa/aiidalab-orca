"""Wavefunction preservation controls shared by submission and post-processing."""
import ipywidgets as ipw
import traitlets as tl
from aiida_empa_orca.artifacts import storage_policy
from .property_services import default_stash_directory, tool_codes


class WavefunctionStorage(ipw.VBox):
    revision=tl.Int()

    def __init__(self):
        choices=tool_codes()['python']
        self.enabled=ipw.Checkbox(value=bool(choices),description='Preserve wavefunction files',layout=ipw.Layout(width='auto'))
        self.threshold=ipw.BoundedFloatText(value=100,min=0,max=10000,description='Retrieve below (MiB)',style={'description_width':'150px'},layout=ipw.Layout(width='300px'))
        self.directory=ipw.Text(value=default_stash_directory(),description='Stash directory',style={'description_width':'150px'},layout=ipw.Layout(width='95%'))
        self.code=ipw.Dropdown(options=choices,description='Storage Python code',style={'description_width':'150px'},layout=ipw.Layout(width='95%'))
        hint=ipw.HTML('<p>Preserve the complete orbital/density bundle in AiiDA when its total size is below the threshold; stash larger bundles at this directory. Stashing copies files; it does not remove the original calculation files.</p>' +
                     ('<p>Configure a local Python code to enable preservation.</p>' if not choices else ''))
        super().__init__([self.enabled,self.threshold,self.directory,self.code,hint])
        for widget in (self.enabled,self.threshold,self.directory,self.code):
            widget.observe(self._changed,names='value')

    def _changed(self,_=None):
        self.revision+=1

    def values(self):
        if not self.enabled.value:
            return None
        if not self.code.value:
            raise ValueError('Select a Python code for electronic-file preservation')
        return {'policy':storage_policy({'threshold_mb':self.threshold.value,'stash_directory':self.directory.value.strip()}),
                'code_uuid':self.code.value}
