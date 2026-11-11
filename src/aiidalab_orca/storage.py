"""Explicit remote/stash policy for new geometry/SCF full native files."""

from .retention import FullFileRetention
from .property_services import default_stash_directory


class WavefunctionStorage(FullFileRetention):
    def __init__(self):
        super().__init__(directory=default_stash_directory())

    def values(self, orca_code_uuid):
        retention = super().values()
        # Keep the historical provenance field for downstream API compatibility;
        # new full-file retention never permits a retrieved electronic bundle.
        return {'policy': {'threshold_mb': 0, 'stash_directory': self.directory.value.strip() or default_stash_directory()},
                'native_output_policy': retention, 'code_uuid': None}
