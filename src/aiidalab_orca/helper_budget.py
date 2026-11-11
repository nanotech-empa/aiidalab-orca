"""Shared serial-helper memory/wall-time controls, independent of science inputs."""
import ipywidgets as ipw
import traitlets as tl
from aiida_empa_orca.rendering import helper_resources
from .resources import MemoryInput,memory_label


class HelperBudget(ipw.VBox):
    revision = tl.Int()

    def __init__(self):
        self.memory=MemoryInput(value=2048,style={'description_width':'initial'})
        self.walltime=ipw.BoundedIntText(value=10,min=1,max=10080,
            description='Wall time (minutes)',style={'description_width':'initial'})
        super().__init__([self.memory,self.walltime])
        for field in (self.memory,self.walltime):field.observe(self._changed,names='value')

    def _changed(self,_=None):
        self.revision+=1

    def values(self):
        return helper_resources({'memory_mb':self.memory.value,'wallclock_seconds':self.walltime.value*60})

    def summary(self):
        p=self.values()
        return f"1 process, {memory_label(p['memory_mb'])}, up to {p['wallclock_seconds']/60:g} minutes"
