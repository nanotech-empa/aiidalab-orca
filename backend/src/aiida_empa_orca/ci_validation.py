"""Submitted comparison of two exported CI solutions in the same orbital basis."""
import json

from aiida import common, engine, orm
from aiida.parsers import Parser

from .dyson import export_location, run_code, script, stage
from .rendering import calcjob_options


class CiComparisonCalculation(engine.CalcJob):
    @classmethod
    def define(cls, spec):
        super().define(spec)
        for key in ('first', 'second', 'location_first', 'location_second'):
            spec.input(key, valid_type=orm.Dict)
        for key in ('source_first', 'source_second'):
            spec.input(key, valid_type=orm.Data)
        spec.input('metadata.options.parser_name', default='empa_orca.ci_comparison')
        spec.input('metadata.options.withmpi', default=False)
        spec.output('validation', valid_type=orm.Dict)
        spec.exit_code(310, 'ERROR_COMPARISON', message='CI solutions failed comparison; inspect comparison.json and driver.log.')

    def prepare_for_submission(self, folder):
        info = common.CalcInfo()
        info.local_copy_list, info.remote_copy_list = [], []
        artifacts, settings = {}, {}
        for key in ('first', 'second'):
            artifact = self.inputs[key]
            producer = artifact.creator
            if (producer is None or not producer.is_finished_ok or
                    producer.process_type != 'aiida.calculations:empa_orca.dyson_export' or
                    producer.computer.uuid != self.inputs.code.computer.uuid):
                raise ValueError('Compare successful native exports on their original computer')
            location = self.inputs['location_'+key].get_dict()
            source = self.inputs['source_'+key]
            if location['uuid'] != str(source.uuid):
                raise ValueError('Export source and location differ')
            stage(info, source, location, key+'.json.gz')
            artifacts[key] = artifact.get_dict()
            settings[key] = producer.inputs.state_energies.creator.inputs.settings.get_dict()
        script(folder, 'compare_ci_solvers.py', {'artifacts':artifacts, 'settings':settings})
        info.codes_info = [run_code(self.inputs.code.uuid, ['compare_ci_solvers.py'], 'driver.log')]
        info.retrieve_list = ['comparison.json', 'driver.log']
        return info


class CiComparisonParser(Parser):
    def parse(self, **kwargs):
        try:
            data = json.loads(self.retrieved.base.repository.get_object_content('comparison.json'))
            self.out('validation', orm.Dict(dict=data))
            if data.get('passed') is not True:
                return self.exit_codes.ERROR_COMPARISON
        except (OSError, KeyError, ValueError) as exc:
            self.logger.error(str(exc))
            return self.exit_codes.ERROR_COMPARISON


def comparison_builder(first_uuid, second_uuid, code_uuid):
    b = CiComparisonCalculation.get_builder()
    b.code = orm.load_code(code_uuid)
    for key, identifier in (('first', first_uuid), ('second', second_uuid)):
        artifact = orm.load_node(identifier)
        location = export_location(artifact)
        b[key] = artifact
        b['source_'+key] = orm.load_node(location['uuid'])
        b['location_'+key] = orm.Dict(dict=location)
    b.metadata.options = calcjob_options(b.first.creator.outputs.remote_folder, seconds=1800)
    b.metadata.options.environment_variables = {'OMP_NUM_THREADS':'1', 'OPENBLAS_NUM_THREADS':'1', 'MKL_NUM_THREADS':'1'}
    b.metadata.disable_cache = True
    b.metadata.label = 'CI solver comparison · raw vectors and degenerate subspaces'
    return b
