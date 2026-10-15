"""Wavefunction preservation controls shared by submission and post-processing."""
import ipywidgets as ipw
import traitlets as tl
from aiida_empa_orca.artifacts import storage_policy
from .property_services import default_stash_directory, helper_code, tool_codes


class WavefunctionStorage(ipw.VBox):
    revision=tl.Int()

    def __init__(self):
        configured=bool(tool_codes()['python'])
        self.enabled=ipw.Checkbox(value=configured,description='Preserve wavefunction files',layout=ipw.Layout(width='auto'))
        self.threshold=ipw.BoundedFloatText(value=100,min=0,max=10000,description='Retrieve below (MiB)',style={'description_width':'150px'},layout=ipw.Layout(width='300px'))
        self.directory=ipw.Text(value=default_stash_directory(),description='Stash directory',style={'description_width':'150px'},layout=ipw.Layout(width='95%'))
        hint=ipw.HTML('<p>Preserve the complete orbital/density bundle in AiiDA when its total size is below the threshold; stash larger bundles at this directory. Stashing copies files; it does not remove the original calculation files.</p>')
        if not configured:
            hint.value+='<p>Preservation requires an ORCA tools application code. Configure it in Code setup to enable this option.</p>'
        super().__init__([self.enabled,self.threshold,self.directory,hint])
        for widget in (self.enabled,self.threshold,self.directory):
            widget.observe(self._changed,names='value')

    def _changed(self,_=None):
        self.revision+=1

    def values(self, orca_code_uuid):
        if not self.enabled.value:
            return None
        from aiida import orm
        code_uuid = helper_code(orm.load_code(orca_code_uuid).computer.uuid)
        return {'policy':storage_policy({'threshold_mb':self.threshold.value,'stash_directory':self.directory.value.strip()}),
                'code_uuid':code_uuid}
