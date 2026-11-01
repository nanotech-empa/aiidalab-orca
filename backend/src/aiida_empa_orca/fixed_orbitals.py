"""A small explicit import step, followed by ordinary native CASCI workflows."""
import json
from pathlib import PurePosixPath
import re

from aiida import common, engine, orm
from aiida.parsers import Parser

from .artifacts import remote_files, storage_builder, storage_policy
from .common_orbitals import options
from .dyson import script, run_code
from .fixed_orbitals_data import PREPARATION, checked_manifest
from .reference import reference_settings


class FixedOrbitalsImportCalculation(engine.CalcJob):
    @classmethod
    def define(cls, spec):
        super().define(spec)
        for key, typ in {'structure':orm.StructureData, 'settings':orm.Dict, 'source_remote':orm.RemoteData,
                         'source_manifest':orm.Dict, 'export_code':orm.AbstractCode}.items():
            spec.input(key, valid_type=typ)
        spec.input('metadata.options.parser_name', default='empa_orca.import_fixed_orbitals')
        spec.input('metadata.options.withmpi', default=False)
        spec.output('orbital_reference', valid_type=orm.Dict)
        spec.exit_code(310, 'ERROR_IMPORT', message='External frozen-orbital validation failed; inspect import.log.')
        spec.exit_code(311, 'ERROR_GBW_FORMAT', message='ORCA could not read this GBW format. Check file integrity and select the matching ORCA exporter/version.')

    def prepare_for_submission(self, folder):
        manifest = checked_manifest(self.inputs.source_manifest.get_dict())
        source = self.inputs.source_remote
        if any(c.computer.uuid != source.computer.uuid for c in (self.inputs.code, self.inputs.export_code)):
            raise ValueError('Import the wavefunction on its source computer')
        info = common.CalcInfo()
        staged = {'gbw':'aiida.gbw', 'input':'source.inp', 'output':'source.out'}
        info.remote_copy_list = [(source.computer.uuid, str(PurePosixPath(source.get_remote_path())/r['name']),
                                  staged[r['role']]) for r in manifest['files']]
        atoms = self.inputs.structure.get_ase()
        request = dict(manifest=manifest, settings=reference_settings(self.inputs.settings.get_dict()),
                       atomic_numbers=atoms.numbers.tolist(), positions=atoms.positions.tolist())
        script(folder, 'import_fixed_orbitals.py', request)
        with folder.open('orca.json.conf','w') as handle:
            json.dump({'MOCoefficients':True, 'Basisset':True, '1elIntegrals':['S'], 'JSONFormats':['json']},handle)
        info.codes_info = [run_code(self.inputs.export_code.uuid, ['aiida.gbw','-json'], 'export.log'),
                           run_code(self.inputs.code.uuid, ['import_fixed_orbitals.py'], 'import.log')]
        info.codes_run_mode = common.CodeRunMode.SERIAL
        info.retrieve_list = ['import_manifest.json','source.inp','source.out','export.log','import.log']
        return info


class FixedOrbitalsImportParser(Parser):
    def parse(self, **kwargs):
        from .casci import active_space, casci_settings, parse_states
        try:
            export_log = self.retrieved.base.repository.get_object_content('export.log')
            if 'Your GBWFile is either corrupt or from a different ORCA version' in export_log:
                self.logger.error(self.exit_codes.ERROR_GBW_FORMAT.message)
                return self.exit_codes.ERROR_GBW_FORMAT
            manifest = checked_manifest(self.node.inputs.source_manifest.get_dict())
            report = json.loads(self.retrieved.base.repository.get_object_content('import_manifest.json'))
            if report['source_manifest'] != manifest:
                raise ValueError('Import manifest differs from its input')
            s = reference_settings(self.node.inputs.settings.get_dict())
            atoms = self.node.inputs.structure.get_ase()
            if (max(atoms.numbers) > 36 or any(v.get('ecp','none').lower() != 'none' for v in s['element_settings'].values()) or
                    report['n_electrons'] != int(sum(atoms.numbers))-s['charge'] or
                    not 0 <= report['active_orthonormality_error'] <= 1e-7):
                raise ValueError('Require a validated all-electron spatial-orbital reference through Kr')
            ref = dict(schema_version=1, preparation=PREPARATION, kind='fixed', filename='aiida.gbw',
                n_orbitals=report['n_orbitals'], n_electrons=report['n_electrons'], charge=s['charge'],
                source_multiplicity=s['multiplicity'], structure_uuid=str(self.node.inputs.structure.uuid),
                settings=s, geometry_mode='fixed', source_manifest=manifest,
                active_space=manifest['active_space'], imported=True)
            space = active_space(manifest['active_space'], ref)
            settings = casci_settings(dict(nroots=manifest['nroots']), ref, space)
            text = self.retrieved.base.repository.get_object_content('source.out')
            basis = re.findall(r'Your calculation utilizes the basis:\s*(\S+)', text)
            counts = re.findall(r'Number of basis functions\s+\.\.\.\s+(\d+)', text)
            if (not basis or basis[-1].casefold() != s['basis'].casefold() or
                    not counts or int(counts[-1]) != ref['n_orbitals']):
                raise ValueError('Imported basis metadata differs from the native output')
            states = parse_states(text, ref, space, settings)['states']
            if any(abs(row['energy_hartree']-energy) > 1e-9 for row,energy in zip(states,manifest['energies_hartree'])):
                raise ValueError('Original CASCI energies differ from the import request')
            self.out('orbital_reference', orm.Dict(dict=ref))
        except (OSError, KeyError, ValueError) as exc:
            self.logger.error(str(exc))
            return self.exit_codes.ERROR_IMPORT


class FixedOrbitalsImportWorkChain(engine.WorkChain):
    @classmethod
    def define(cls, spec):
        super().define(spec)
        for key, typ in {'structure':orm.StructureData, 'settings':orm.Dict, 'code':orm.AbstractCode,
                         'source_remote':orm.RemoteData, 'source_manifest':orm.Dict,
                         'export_code':orm.AbstractCode, 'storage_code':orm.AbstractCode,
                         'storage_policy':orm.Dict}.items():
            spec.input(key, valid_type=typ)
        for key, typ in {'structure':orm.StructureData, 'orbital_reference':orm.Dict,
                         'remote_folder':orm.RemoteData, 'retrieved':orm.FolderData}.items():
            spec.output(key, valid_type=typ)
        spec.outline(cls.setup, cls.import_reference, cls.inspect, cls.preserve, cls.results)
        spec.exit_code(400, 'ERROR_SOURCE', message='External reference files or import inputs are unavailable.')
        spec.exit_code(401, 'ERROR_IMPORT', message='External fixed-orbital checks failed.')
        spec.exit_code(402, 'ERROR_STORAGE', message='Imported orbital availability could not be recorded.')

    def setup(self):
        try:
            data = checked_manifest(self.inputs.source_manifest.get_dict())
            if storage_policy(self.inputs.storage_policy.get_dict()).get('mode') != 'remote':
                raise ValueError('This import preserves the GBW in its working directory; select remote-only storage')
            source = self.inputs.source_remote
            if any(self.inputs[k].computer.uuid != source.computer.uuid for k in ('code','storage_code','export_code')):
                raise ValueError('All import and future ORCA codes must use the source computer')
            remote_files(source.computer, source.get_remote_path(), names=[r['name'] for r in data['files']],
                         expected={r['name']:r['size_bytes'] for r in data['files']})
        except (OSError, KeyError, ValueError, RuntimeError) as exc:
            self.report(str(exc))
            return self.exit_codes.ERROR_SOURCE

    def import_reference(self):
        b = FixedOrbitalsImportCalculation.get_builder()
        for key in ('structure','settings','source_remote','source_manifest','export_code'):
            b[key] = self.inputs[key]
        b.code = self.inputs.storage_code
        s = self.inputs.settings.get_dict()
        b.metadata.options = options(s) | {'resources':{'num_machines':1,'num_mpiprocs_per_machine':1},
                                          'max_wallclock_seconds':1800}
        b.metadata.disable_cache = True
        return engine.ToContext(imported=self.submit(b))

    def inspect(self):
        if not self.ctx.imported.is_finished_ok:
            self.report(self.ctx.imported.exit_message or 'Import validation failed; inspect the child calculation logs.')
            return self.exit_codes.ERROR_IMPORT

    def preserve(self):
        return engine.ToContext(storage=self.submit(storage_builder(self.ctx.imported.outputs.remote_folder,
            self.inputs.storage_code, self.inputs.storage_policy.get_dict(), names=['aiida.gbw'])))

    def results(self):
        if not self.ctx.storage.is_finished_ok:
            return self.exit_codes.ERROR_STORAGE
        self.out('structure', self.inputs.structure)
        for key in ('orbital_reference','remote_folder','retrieved'):
            self.out(key, self.ctx.imported.outputs[key])
