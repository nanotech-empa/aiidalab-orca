"""Verify Co cores without passing a CASSCF wavefunction through UKS GUESS."""
import json
from importlib.resources import files

from aiida import common, engine, orm
from aiida.parsers import Parser

from . import cobalt_xps as co
from .scripts.casscf_core import core_reference


def source_calculation(structure, reference, retrieved, code):
    producer = reference.creator
    if (producer is None or producer.process_type != co.CALC_PROCESS
            or producer.inputs.stage.value != 'spectator'
            or producer.outputs.reference.uuid != reference.uuid
            or producer.outputs.retrieved.uuid != retrieved.uuid
            or producer.inputs.structure.uuid != structure.uuid
            or producer.inputs.code.computer.uuid != code.computer.uuid):
        raise ValueError('Co core assignment requires the exact spectator calculation, geometry and native output')
    co.validated_calculation(producer)
    return str(producer.uuid)


class CobaltCoreCalculation(engine.CalcJob):
    @classmethod
    def define(cls, spec):
        super().define(spec)
        for key, kind in {'structure': orm.StructureData, 'source_reference': orm.Dict,
                          'source_retrieved': orm.FolderData}.items():
            spec.input(key, valid_type=kind)
        spec.input('metadata.options.withmpi', default=False)
        spec.input('metadata.options.parser_name', default='empa_orca.cobalt_core')
        spec.output('core_reference', valid_type=orm.Dict)
        spec.exit_code(310, 'ERROR_CORE', message='Native CASSCF Co core assignment failed; inspect core.log.')

    def prepare_for_submission(self, folder):
        uid = source_calculation(self.inputs.structure, self.inputs.source_reference,
                                 self.inputs.source_retrieved, self.inputs.code)
        numbers = self.inputs.structure.get_ase().numbers.tolist()
        # Validate before queueing as well as after remote execution.
        core_reference(self.inputs.source_retrieved.base.repository.get_object_content('aiida.out'), numbers, uid)
        for name in ('core_orbitals.py', 'casscf_core.py'):
            with folder.open(name, 'w') as handle:
                handle.write(files('aiida_empa_orca').joinpath('scripts', name).read_text())
        with folder.open('request.json', 'w') as handle:
            json.dump({'kind': 'native_casscf_co', 'numbers': numbers, 'source_calculation_uuid': uid}, handle)
        info = common.CalcInfo()
        info.local_copy_list = [(str(self.inputs.source_retrieved.uuid), 'aiida.out', 'aiida.out')]
        code = common.CodeInfo()
        code.code_uuid, code.cmdline_params = self.inputs.code.uuid, ['core_orbitals.py']
        code.stdout_name, code.join_files = 'core.log', True
        info.codes_info = [code]
        info.retrieve_list = ['core.json', 'core.log']
        return info


class CobaltCoreParser(Parser):
    def parse(self, **kwargs):
        try:
            uid = source_calculation(self.node.inputs.structure, self.node.inputs.source_reference,
                                     self.node.inputs.source_retrieved, self.node.inputs.code)
            text = self.node.inputs.source_retrieved.base.repository.get_object_content('aiida.out')
            expected = core_reference(text, self.node.inputs.structure.get_ase().numbers.tolist(), uid)
            data = json.loads(self.retrieved.base.repository.get_object_content('core.json'))
            if data != expected:
                raise ValueError('Stored Co core assignments differ from the producing CASSCF output')
            self.out('core_reference', orm.Dict(dict=data))
        except (ValueError, KeyError, OSError) as exc:
            self.logger.error(str(exc))
            return self.exit_codes.ERROR_CORE
