"""A small, reusable preparation step for a shared spatial-orbital basis.

No geometry or SCF optimization is performed. Restricted orbitals are read as-is;
unrestricted orbitals are converted to ORCA quasi-restricted orbitals (UNO/QRO).
"""

import re
from pathlib import PurePosixPath

from aiida import common, engine, orm
from aiida.parsers import Parser
from aiida_orca.calculations.orca_orca import OrcaCalculation

from .artifacts import resolve_electronic, storage_builder, storage_policy
from .input import render_input
from .protocols import reference as reference_type
from .reference import reference_settings, reference_signature, single_point_parameters

PROCESS_TYPE = 'aiida.workflows:empa_orca.common_orbitals'


def preparation_parameters(settings):
    s = reference_settings(settings)
    parameters = single_point_parameters(s)
    parameters['input_keywords'] += ['MOREAD', 'NoIter']
    # An explicit SCF MaxIter from the source would override NoIter.
    parameters['input_blocks']['scf'] = {key:value for key,value in parameters['input_blocks']['scf'].items()
                                       if key.lower() not in ('maxiter', 'guessmix')}
    parameters['input_blocks']['scf']['MaxIter'] = 0
    if reference_type(s).startswith('U'):
        parameters['input_keywords'].append('UNO')
    return parameters


def orbital_filename(settings):
    return 'aiida.qro' if reference_type(reference_settings(settings)).startswith('U') else 'aiida.gbw'


def copy_orbital(info, inputs, target='reference.gbw'):
    """Stage a single file from a checked remote, stashed or retrieved bundle."""
    keys = [key for key in ('source_repository', 'source_stash', 'source_folder') if key in inputs]
    if len(keys) != 1:
        raise ValueError('Exactly one orbital-file location is required')
    name = inputs.source_filename.value
    if name not in ('aiida.gbw', 'aiida.qro'):
        raise ValueError('Unsupported orbital filename')
    source = inputs[keys[0]]
    if keys[0] == 'source_repository':
        info.local_copy_list = [(source.uuid, 'electronic/'+name, target)]
    else:
        if source.computer.uuid != inputs.code.computer.uuid:
            raise ValueError('Remote orbitals and ORCA must use the same computer')
        base = (PurePosixPath(source.target_basepath)/'electronic' if keys[0] == 'source_stash'
                else PurePosixPath(source.get_remote_path()))
        info.remote_copy_list = [(source.computer.uuid, str(base/name), target)]


def source_spec(spec):
    spec.input('source_repository', valid_type=orm.FolderData, required=False)
    spec.input('source_stash', valid_type=orm.RemoteStashFolderData, required=False)
    spec.input('source_folder', valid_type=orm.RemoteData, required=False)
    spec.input('source_filename', valid_type=orm.Str)


def attach_orbital(builder, location, filename):
    key = {'repository':'source_repository', 'stash':'source_stash', 'remote':'source_folder'}[location['kind']]
    builder[key] = orm.load_node(location['uuid'])
    builder.source_filename = orm.Str(filename)


def options(settings):
    return {'resources': {'num_machines': 1, 'num_mpiprocs_per_machine': settings['nprocs']},
            'withmpi': False, 'max_wallclock_seconds': settings['wallclock_seconds'],
            'max_memory_kb': settings['memory_mb']*1024}


def validate_source(structure, settings, code, retrieved, remote):
    """Require the original geometry/settings and actual producing CalcJob."""
    producer = retrieved.creator
    if producer is None or producer.outputs.remote_folder.uuid != remote.uuid:
        raise ValueError('Output and orbital folder have different producers')
    from .reference import PROCESS_TYPE as SCF_PROCESS, GEOMETRY_PROCESS
    expected = reference_signature(structure, settings, code.uuid)
    for triple in retrieved.base.links.get_incoming(link_type=common.LinkType.RETURN).all():
        node = triple.node
        if node.process_type not in (SCF_PROCESS, GEOMETRY_PROCESS) or 'structure' not in node.outputs:
            continue
        if reference_signature(node.outputs.structure, node.inputs.settings.get_dict(), node.inputs.code.uuid) == expected:
            return
    raise ValueError('The molecular geometry, settings and code must match the SCF producer')


class CommonOrbitalsCalculation(engine.CalcJob):
    @classmethod
    def define(cls, spec):
        super().define(spec)
        spec.input('structure', valid_type=orm.StructureData)
        spec.input('settings', valid_type=orm.Dict)
        spec.input('source_retrieved', valid_type=orm.FolderData)
        source_spec(spec)
        spec.input('metadata.options.parser_name', default='empa_orca.common_orbitals')
        spec.input('metadata.options.withmpi', default=False)
        spec.output('orbital_reference', valid_type=orm.Dict)
        spec.exit_code(310, 'ERROR_REFERENCE', message='Common-orbital preparation failed; inspect aiida.out.')

    def prepare_for_submission(self, folder):
        s = reference_settings(self.inputs.settings.get_dict())
        params = preparation_parameters(s)
        text = '%moinp "reference.gbw"\n' + render_input(params, int(.75*s['memory_mb']/s['nprocs']), 'aiida.coords.xyz')
        with folder.open('aiida.inp', 'w') as handle:
            handle.write(text)
        OrcaCalculation._write_structure(self.inputs.structure, folder, 'aiida.coords.xyz')
        info = common.CalcInfo()
        copy_orbital(info, self.inputs)
        code = common.CodeInfo()
        code.code_uuid, code.cmdline_params = self.inputs.code.uuid, ['aiida.inp']
        code.stdout_name, code.join_files = 'aiida.out', True
        info.codes_info, info.retrieve_list = [code], ['aiida.out']
        return info


class CommonOrbitalsParser(Parser):
    def parse(self, **kwargs):
        try:
            text = self.retrieved.base.repository.get_object_content('aiida.out')
            if 'ORCA TERMINATED NORMALLY' not in text:
                raise ValueError('ORCA did not terminate normally')
            if ('MaxIter==0 has been chosen - skipping the SCF' not in text or
                    re.search(r'SCF CONVERGED AFTER\s+[1-9]\d*\s+CYCLES', text)):
                raise ValueError('Unexpected SCF iterations during orbital preparation')
            s = reference_settings(self.node.inputs.settings.get_dict())
            # ORCA echoes the input filename, but this verifies it really read MOs.
            if not re.search(r'Guess MOs are being read from file: reference\.gbw', text, re.I):
                raise ValueError('No confirmation of reading the supplied orbitals')
            if ('Input Geometry matches current geometry' not in text or
                    'Input basis set matches current basis set' not in text):
                raise ValueError('ORCA did not confirm matching geometry and basis')
            counts = re.findall(r'Number of (?:basis functions|contracted basis functions)\s*\.*\s*(\d+)', text, re.I)
            if not counts:
                raise ValueError('No spatial-orbital dimension')
            filename = orbital_filename(s)
            if filename.endswith('qro') and 'Quasi-Restricted Orbitals were saved in aiida.qro' not in text:
                raise ValueError('ORCA did not confirm QRO generation')
            from .artifacts import remote_files
            remote_files(self.node.computer, self.node.outputs.remote_folder.get_remote_path(), names=[filename])
            electrons = int(self.node.inputs.structure.get_ase().numbers.sum())-s['charge']
            counts_e = re.findall(r'Number of Electrons\s+NEL\s+\.+\s*(\d+)',text)
            if not counts_e or int(counts_e[-1]) != electrons:
                raise ValueError('Electron count differs from the all-electron reference; ECPs are not yet supported')
            self.out('orbital_reference', orm.Dict(dict={
                'schema_version': 1, 'preparation':'moread_noiter_v1', 'kind': 'QRO' if filename.endswith('qro') else 'restricted',
                'filename': filename, 'n_orbitals': int(counts[-1]), 'n_electrons': electrons,
                'charge': s['charge'], 'source_multiplicity': s['multiplicity'],
                'structure_uuid': str(self.node.inputs.structure.uuid),
                'source_retrieved_uuid': str(self.node.inputs.source_retrieved.uuid),
                'settings': s, 'geometry_mode': 'fixed'}))
        except (KeyError, ValueError, OSError) as exc:
            self.logger.error(str(exc))
            return self.exit_codes.ERROR_REFERENCE


def reference_location(node):
    if not node.is_finished_ok or 'orbital_reference' not in node.outputs:
        raise ValueError('Common-orbital preparation did not finish successfully')
    name = node.outputs.orbital_reference.get_dict()['filename']
    return resolve_electronic(node.outputs.remote_folder, names=[name])


def matching_references(retrieved_uuid, code_uuid):
    query = orm.QueryBuilder().append(orm.FolderData, filters={'uuid': str(retrieved_uuid)}, tag='source').append(
        orm.WorkChainNode, with_incoming='source', edge_filters={'label':'source_retrieved'}, tag='run',
        filters={'process_type': PROCESS_TYPE, 'attributes.process_state':'finished', 'attributes.exit_status':0}, project=['uuid'])
    for uuid in query.order_by({'run':{'ctime':'desc'}}).all(flat=True):
        node = orm.load_node(uuid)
        if (str(node.inputs.code.uuid) == str(code_uuid) and
                node.outputs.orbital_reference.get_dict().get('preparation') == 'moread_noiter_v1'):
            yield str(uuid)


class CommonOrbitalsWorkChain(engine.WorkChain):
    @classmethod
    def define(cls, spec):
        super().define(spec)
        for key, typ in {'structure':orm.StructureData, 'settings':orm.Dict, 'code':orm.AbstractCode,
                         'source_retrieved':orm.FolderData, 'source_remote':orm.RemoteData,
                         'storage_code':orm.AbstractCode, 'storage_policy':orm.Dict}.items():
            spec.input(key, valid_type=typ)
        spec.input('force_recompute', valid_type=orm.Bool, default=lambda:orm.Bool(False))
        for key, typ in {'orbital_reference':orm.Dict, 'remote_folder':orm.RemoteData, 'retrieved':orm.FolderData}.items():
            spec.output(key, valid_type=typ)
        spec.outline(cls.setup, engine.if_(cls.needs_preparation)(cls.prepare, cls.inspect,
                     cls.preserve, cls.inspect_storage), cls.results)
        spec.exit_code(400, 'ERROR_SOURCE', message='The source orbitals or provenance are unavailable; see report.')
        spec.exit_code(401, 'ERROR_PREPARATION', message='Common spatial-orbital preparation failed.')
        spec.exit_code(402, 'ERROR_STORAGE', message='Common-orbital preservation failed.')

    def setup(self):
        self.ctx.reuse_uuid = None
        try:
            validate_source(self.inputs.structure, self.inputs.settings.get_dict(), self.inputs.code,
                            self.inputs.source_retrieved, self.inputs.source_remote)
            storage_policy(self.inputs.storage_policy.get_dict())
            if self.inputs.storage_code.computer.uuid != self.inputs.code.computer.uuid:
                raise ValueError('Storage and ORCA codes must use the same computer')
            # The first implementation requires all-electron basis electron counting.
            s = reference_settings(self.inputs.settings.get_dict())
            if (max(self.inputs.structure.get_ase().numbers) > 36 or
                    any(v.get('ecp', 'none').lower() != 'none' for v in s['element_settings'].values())):
                raise ValueError('This CASCI draft supports all-electron molecules through Kr; ECP references need explicit core-electron accounting')
            if not self.inputs.force_recompute.value:
                for uuid in matching_references(self.inputs.source_retrieved.uuid, self.inputs.code.uuid):
                    node = orm.load_node(uuid)
                    try:
                        reference_location(node)
                    except (FileNotFoundError, ValueError, KeyError):
                        continue
                    self.ctx.reuse_uuid = uuid
                    self.report(f'Reusing available common orbitals from {uuid}')
                    return
            self.ctx.location = resolve_electronic(self.inputs.source_remote)
        except (KeyError, ValueError, OSError, RuntimeError) as exc:
            self.report(str(exc))
            return self.exit_codes.ERROR_SOURCE

    def needs_preparation(self):
        return self.ctx.reuse_uuid is None

    def prepare(self):
        b = CommonOrbitalsCalculation.get_builder()
        for key in ('structure', 'settings', 'code', 'source_retrieved'):
            b[key] = self.inputs[key]
        attach_orbital(b, self.ctx.location, 'aiida.gbw')
        b.metadata.options = options(self.inputs.settings.get_dict())
        # Preparation creates a remote artifact. Explicit reuse above checks it;
        # never accept a cached directory whose QRO/GBW may have disappeared.
        b.metadata.disable_cache = True
        return engine.ToContext(preparation=self.submit(b))

    def inspect(self):
        if not self.ctx.preparation.is_finished_ok:
            return self.exit_codes.ERROR_PREPARATION

    def preserve(self):
        node = self.ctx.preparation
        filename = node.outputs.orbital_reference.get_dict()['filename']
        b = storage_builder(node.outputs.remote_folder, self.inputs.storage_code,
                            self.inputs.storage_policy.get_dict(),
                            names=[filename,'aiida.uno'] if filename.endswith('qro') else [filename])
        return engine.ToContext(storage=self.submit(b))

    def inspect_storage(self):
        if not self.ctx.storage.is_finished_ok:
            return self.exit_codes.ERROR_STORAGE

    def results(self):
        node = orm.load_node(self.ctx.reuse_uuid) if self.ctx.reuse_uuid else self.ctx.preparation
        for key in ('orbital_reference', 'remote_folder', 'retrieved'):
            self.out(key, node.outputs[key])
