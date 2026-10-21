"""Inspect preserved QRO/UNO files and generate cubes through the shared pipeline."""
import json
import math
from importlib.resources import files
from pathlib import PurePosixPath

from aiida import common, engine, orm
from aiida.parsers import Parser

from .artifacts import resolve_electronic, storage_builder, storage_policy
from .orbitals import OrbitalCubesCalculation, attach_source, cube_parameters, validate_cube_outputs
from .rendering import calcjob_options
from .fixed_orbitals_data import CALCULATION as IMPORT_CALCULATION, PREPARATION as IMPORT_PREPARATION

CATALOG_PROCESS = 'aiida.workflows:empa_orca.orbital_catalog'
CUBES_PROCESS = 'aiida.workflows:empa_orca.common_orbital_cubes'
HARTREE_TO_EV = 27.211386245988


def validate_reference(reference, remote):
    producer = reference.creator
    if (producer is None or not producer.is_finished_ok or producer.process_type not in (
            'aiida.calculations:empa_orca.common_orbitals', IMPORT_CALCULATION) or
            producer.outputs.remote_folder.uuid != remote.uuid):
        raise ValueError('The orbital reference and folder must have the same preparation producer')
    data = reference.get_dict()
    expected = IMPORT_PREPARATION if producer.process_type == IMPORT_CALCULATION else 'moread_noiter_v1'
    if data.get('preparation') != expected:
        raise ValueError('Select a verified fixed-orbital preparation')
    return data


def variants(reference):
    if reference.get('preparation') == IMPORT_PREPARATION:
        return {'fixed':'aiida.gbw'}
    if reference['filename'] == 'aiida.qro':
        return {'QRO':'aiida.qro', 'UNO':'aiida.uno'}
    return {'restricted':'aiida.gbw'}


def parse_catalog(raw, reference, structure):
    """Validate spatial dimensions, electron counts and the source geometry."""
    result = {}
    atoms = structure.get_ase()
    for kind, value in raw['sets'].items():
        if kind not in variants(reference) or value['source_filename'] != variants(reference)[kind]:
            raise ValueError('Unknown orbital set in export')
        molecule = value['molecule']
        exported = molecule['Atoms']
        if molecule['CoordinateUnits'] not in ('Angs', 'Angstrom'):
            raise ValueError('Unsupported ORCA geometry units in orbital export')
        if (len(exported) != len(atoms) or
                [row['ElementNumber'] for row in exported] != atoms.numbers.tolist() or
                any(len(row['Coords']) != 3 or not all(math.isfinite(float(x)) for x in row['Coords']) for row in exported) or
                any(abs(float(x)-float(y)) > 1e-7 for row, position in zip(exported,atoms.positions)
                    for x,y in zip(row['Coords'],position))):
            raise ValueError('Orbital-file geometry differs from the reference')
        if molecule['Charge'] != reference['charge'] or molecule['Multiplicity'] != reference['source_multiplicity']:
            raise ValueError('Orbital-file charge/spin differs from the reference')
        table = molecule['MolecularOrbitals']
        if table['EnergyUnit'] != 'Eh' or len(table['MOs']) != reference['n_orbitals']:
            raise ValueError('Incomplete spatial-orbital table or unsupported energy units')
        levels = []
        for index, row in enumerate(table['MOs']):
            occupation = float(row['Occupancy'])
            if not math.isfinite(occupation) or not -1e-7 <= occupation <= 2+1e-7:
                raise ValueError('Invalid spatial-orbital occupation')
            level = {'index':index, 'occupation':occupation}
            if kind not in ('UNO','fixed'):
                energy = float(row['OrbitalEnergy'])
                if not math.isfinite(energy) or abs(occupation-round(occupation)) > 1e-6:
                    raise ValueError('Invalid reference occupation or orbital energy')
                level['energy_ev'] = energy*HARTREE_TO_EV
            levels.append(level)
        if abs(sum(row['occupation'] for row in levels)-reference['n_electrons']) > 1e-5:
            raise ValueError('Orbital occupations do not sum to the reference electron count')
        result[kind] = {'filename':value['source_filename'], 'sha256':value['sha256'],
                        'size_bytes':value['size_bytes'], 'levels':levels,
                        'occupation_kind':('fractional_natural' if kind == 'UNO' else
                                           'source_casci_diagonal' if kind == 'fixed' else 'integer_reference')}
    if not result:
        raise ValueError('No orbital information was exported')
    return result


def same_orbital_set(first, second, kind):
    """Repeated metadata reads do not change a preserved orbital-file identity."""
    return (first.get('orbital_reference_uuid') == second.get('orbital_reference_uuid') and
            first.get('sets',{}).get(kind) == second.get('sets',{}).get(kind) and
            kind in first.get('sets',{}))


def runs(reference_uuid, process_type=CATALOG_PROCESS):
    return orm.QueryBuilder().append(orm.Dict,filters={'uuid':str(reference_uuid)},tag='reference').append(
        orm.WorkChainNode,with_incoming='reference',edge_filters={'label':'orbital_reference'},tag='run',
        filters={'process_type':process_type},project=['uuid']).order_by({'run':{'ctime':'desc'}}).all(flat=True)


class OrbitalCatalogCalculation(engine.CalcJob):
    @classmethod
    def define(cls, spec):
        super().define(spec)
        spec.input('orbital_reference',valid_type=orm.Dict)
        spec.input('source_remote',valid_type=orm.RemoteData)
        spec.input('helper_code',valid_type=orm.AbstractCode)
        spec.input('locations',valid_type=orm.Dict)
        spec.input_namespace('sources',dynamic=True,valid_type=orm.Data)
        spec.input('metadata.options.parser_name',default='empa_orca.orbital_catalog')
        spec.input('metadata.options.withmpi',default=False)
        spec.output('catalog',valid_type=orm.Dict)
        spec.exit_code(310,'ERROR_CATALOG',message='Orbital inspection failed; inspect the export logs.')

    def prepare_for_submission(self, folder):
        validate_reference(self.inputs.orbital_reference,self.inputs.source_remote)
        if self.inputs.helper_code.computer.uuid != self.inputs.code.computer.uuid:
            raise ValueError('Export and ORCA tools must use the same computer')
        info = common.CalcInfo()
        info.local_copy_list, info.remote_copy_list, codes, request = [], [], [], {'sets':{}}
        for kind, location in self.inputs.locations.get_dict().items():
            name = variants(self.inputs.orbital_reference.get_dict())[kind]
            item = next(row for row in location['files'] if row['name'] == name)
            source = self.inputs.sources[kind.lower()]
            staged = kind.lower()+'.gbw'
            if location['kind'] == 'repository':
                info.local_copy_list.append((source.uuid,'electronic/'+name,staged))
            else:
                if source.computer.uuid != self.inputs.code.computer.uuid:
                    raise ValueError('Read remote orbital files on their storage computer')
                base = (PurePosixPath(source.target_basepath)/'electronic' if location['kind'] == 'stash'
                        else PurePosixPath(source.get_remote_path()))
                info.remote_copy_list.append((source.computer.uuid,str(base/name),staged))
            request['sets'][kind] = dict(item,staged=staged)
            code = common.CodeInfo()
            code.code_uuid, code.cmdline_params = self.inputs.code.uuid, [staged,'-json']
            code.stdout_name, code.join_files = kind.lower()+'.log', True
            codes.append(code)
        with folder.open('request.json','w') as handle:
            json.dump(request,handle)
        with folder.open('orca.json.conf','w') as handle:
            json.dump({'MOCoefficients':True,'BasisSet':False},handle)
        with folder.open('compact_orbitals.py','w') as handle:
            handle.write(files('aiida_empa_orca').joinpath('scripts/compact_orbitals.py').read_text())
        code = common.CodeInfo()
        code.code_uuid, code.cmdline_params = self.inputs.helper_code.uuid, ['compact_orbitals.py']
        code.stdout_name, code.join_files = 'inspection.log', True
        codes.append(code)
        info.codes_info, info.codes_run_mode = codes, common.CodeRunMode.SERIAL
        info.retrieve_list = ['orbital_metadata.json','inspection.log']+[kind.lower()+'.log' for kind in request['sets']]
        return info


class OrbitalCatalogParser(Parser):
    def parse(self, **kwargs):
        try:
            reference = validate_reference(self.node.inputs.orbital_reference,self.node.inputs.source_remote)
            raw = json.loads(self.retrieved.base.repository.get_object_content('orbital_metadata.json'))
            if set(raw['sets']) != set(self.node.inputs.locations.get_dict()):
                raise ValueError('Incomplete orbital export')
            structure = self.node.inputs.orbital_reference.creator.inputs.structure
            sets = parse_catalog(raw,reference,structure)
            self.out('catalog',orm.Dict(dict={'schema_version':1,'sets':sets,
                'orbital_reference_uuid':str(self.node.inputs.orbital_reference.uuid),
                'source_remote_uuid':str(self.node.inputs.source_remote.uuid),
                'structure_uuid':str(structure.uuid), 'n_electrons':reference['n_electrons'],
                'n_orbitals':reference['n_orbitals']}))
        except (KeyError,ValueError,OSError) as exc:
            self.logger.error(str(exc))
            return self.exit_codes.ERROR_CATALOG


class OrbitalCatalogWorkChain(engine.WorkChain):
    @classmethod
    def define(cls, spec):
        super().define(spec)
        for key,typ in {'orbital_reference':orm.Dict,'source_remote':orm.RemoteData,'export_code':orm.AbstractCode,
                        'storage_code':orm.AbstractCode,'storage_policy':orm.Dict}.items():
            spec.input(key,valid_type=typ)
        spec.input('force_recompute',valid_type=orm.Bool,default=lambda:orm.Bool(False))
        spec.output('catalog',valid_type=orm.Dict)
        spec.outline(cls.setup,engine.if_(cls.needs_execution)(cls.preserve,cls.export,cls.inspect),cls.results)
        spec.exit_code(400,'ERROR_SOURCE',message='Orbital files are unavailable; see the workflow report.')
        spec.exit_code(401,'ERROR_STORAGE',message='Orbital-file preservation failed.')
        spec.exit_code(402,'ERROR_CATALOG',message='Orbital metadata export failed.')

    def setup(self):
        self.ctx.reuse_uuid, self.ctx.locations = None, {}
        try:
            ref = validate_reference(self.inputs.orbital_reference,self.inputs.source_remote)
            storage_policy(self.inputs.storage_policy.get_dict())
            if any(self.inputs[key].computer.uuid != self.inputs.source_remote.computer.uuid
                   for key in ('export_code','storage_code')):
                raise ValueError('Export orbitals on the reference computer')
            if not self.inputs.force_recompute.value:
                for uuid in runs(self.inputs.orbital_reference.uuid):
                    old = orm.load_node(uuid)
                    if (old.is_finished_ok and old.inputs.export_code.uuid == self.inputs.export_code.uuid and
                            old.inputs.storage_code.uuid == self.inputs.storage_code.uuid):
                        self.ctx.reuse_uuid = str(uuid)
                        self.report(f'Reusing durable orbital metadata from {uuid}')
                        return
            for kind,name in variants(ref).items():
                try:
                    self.ctx.locations[kind] = resolve_electronic(self.inputs.source_remote,names=[name])
                except (OSError,ValueError,KeyError) as exc:
                    self.report(f'{kind} unavailable: {exc}. Prepare a new reference if regeneration is needed.')
            if not self.ctx.locations:
                return self.exit_codes.ERROR_SOURCE
        except (OSError,ValueError,KeyError,RuntimeError) as exc:
            self.report(str(exc))
            return self.exit_codes.ERROR_SOURCE

    def needs_execution(self):
        return self.ctx.reuse_uuid is None

    def preserve(self):
        pending = {}
        for kind,location in self.ctx.locations.items():
            if location['kind'] == 'remote':
                name = variants(self.inputs.orbital_reference.get_dict())[kind]
                b = storage_builder(self.inputs.source_remote,self.inputs.storage_code,
                                    self.inputs.storage_policy.get_dict(),names=[name])
                pending['storage_'+kind] = self.submit(b)
        return engine.ToContext(**pending)

    def export(self):
        for kind in self.ctx.locations:
            key = 'storage_'+kind
            if key in self.ctx and not self.ctx[key].is_finished_ok:
                return self.exit_codes.ERROR_STORAGE
        b = OrbitalCatalogCalculation.get_builder()
        b.code, b.helper_code = self.inputs.export_code,self.inputs.storage_code
        b.orbital_reference, b.source_remote = self.inputs.orbital_reference,self.inputs.source_remote
        locations = {}
        for kind in self.ctx.locations:
            name = variants(self.inputs.orbital_reference.get_dict())[kind]
            location = resolve_electronic(self.inputs.source_remote,names=[name])
            locations[kind] = location
            b.sources[kind.lower()] = orm.load_node(location['uuid'])
        b.locations = orm.Dict(dict=locations)
        b.metadata.options = calcjob_options(self.inputs.source_remote,seconds=1800)
        b.metadata.disable_cache = True
        return engine.ToContext(extraction=self.submit(b))

    def inspect(self):
        if not self.ctx.extraction.is_finished_ok:
            return self.exit_codes.ERROR_CATALOG

    def results(self):
        node = orm.load_node(self.ctx.reuse_uuid) if self.ctx.reuse_uuid else self.ctx.extraction
        self.out('catalog',node.outputs.catalog)


class CommonOrbitalCubesWorkChain(engine.WorkChain):
    @classmethod
    def define(cls, spec):
        super().define(spec)
        for key,typ in {'orbital_reference':orm.Dict,'source_remote':orm.RemoteData,'catalog':orm.Dict,
                        'orbital_kind':orm.Str,'parameters':orm.Dict,'storage_policy':orm.Dict,
                        'storage_code':orm.AbstractCode,'plot_code':orm.AbstractCode,'cubehandler_code':orm.AbstractCode}.items():
            spec.input(key,valid_type=typ)
        for key,typ in {'manifest':orm.Dict,'retrieved':orm.FolderData,'remote_folder':orm.RemoteData,
                        'remote_stash':orm.RemoteStashFolderData}.items():
            spec.output(key,valid_type=typ,required=key != 'remote_stash')
        spec.outline(cls.setup,engine.if_(cls.needs_execution)(cls.preserve,cls.generate,cls.inspect),cls.results)
        spec.exit_code(400,'ERROR_SOURCE',message='Orbital cubes could not be prepared; see report.')
        spec.exit_code(401,'ERROR_CUBES',message='Orbital cube generation or reduction failed.')

    def setup(self):
        self.ctx.reuse_uuid = None
        try:
            validate_reference(self.inputs.orbital_reference,self.inputs.source_remote)
            data = self.inputs.catalog.get_dict()
            producer = self.inputs.catalog.creator
            if (producer is None or producer.process_type != 'aiida.calculations:empa_orca.orbital_catalog' or
                    producer.inputs.orbital_reference.uuid != self.inputs.orbital_reference.uuid or
                    data['source_remote_uuid'] != str(self.inputs.source_remote.uuid)):
                raise ValueError('Orbital catalog does not belong to this preparation')
            p = cube_parameters(self.inputs.parameters.get_dict())
            kind = self.inputs.orbital_kind.value
            selected = data['sets'][kind]
            if p['spin_density'] or any(spin != 0 or index >= len(selected['levels']) for spin,index in p['orbitals']):
                raise ValueError('Select spatial orbitals from the catalog; QRO/UNO files do not supply the original spin density')
            if any(self.inputs[key].computer.uuid != self.inputs.source_remote.computer.uuid
                   for key in ('storage_code','plot_code','cubehandler_code')):
                raise ValueError('Generate orbitals on their storage computer')
            storage_policy(self.inputs.storage_policy.get_dict())
            self.ctx.parameters = p
            for uuid in runs(self.inputs.orbital_reference.uuid,CUBES_PROCESS):
                old = orm.load_node(uuid)
                if (old.is_finished_ok and same_orbital_set(old.inputs.catalog.get_dict(),data,kind) and
                        old.inputs.orbital_kind.value == kind and cube_parameters(old.inputs.parameters.get_dict()) == p and
                        all(old.inputs[key].uuid == self.inputs[key].uuid for key in ('storage_code','plot_code','cubehandler_code'))):
                    try:
                        validate_cube_outputs(old)
                    except (OSError,ValueError,KeyError):
                        continue
                    self.ctx.reuse_uuid = str(uuid)
                    self.report(f'Reusing verified {kind} cubes from {uuid}')
                    return
            location = resolve_electronic(self.inputs.source_remote,names=[selected['filename']])
            item = next(item for item in location['files'] if item['name'] == selected['filename'])
            if item['size_bytes'] != selected['size_bytes'] or (item.get('sha256') and item['sha256'] != selected['sha256']):
                raise ValueError('The orbital file differs from the inspected catalog; inspect it again')
            self.ctx.location = location
        except (OSError,ValueError,KeyError,RuntimeError) as exc:
            self.report(str(exc))
            return self.exit_codes.ERROR_SOURCE

    def needs_execution(self):
        return self.ctx.reuse_uuid is None

    def preserve(self):
        if self.ctx.location['kind'] == 'remote':
            name = self.inputs.catalog.get_dict()['sets'][self.inputs.orbital_kind.value]['filename']
            return engine.ToContext(storage=self.submit(storage_builder(self.inputs.source_remote,self.inputs.storage_code,
                                       self.inputs.storage_policy.get_dict(),names=[name])))

    def generate(self):
        if 'storage' in self.ctx and not self.ctx.storage.is_finished_ok:
            return self.exit_codes.ERROR_SOURCE
        kind = self.inputs.orbital_kind.value
        data = self.inputs.catalog.get_dict()
        selected = data['sets'][kind]
        location = resolve_electronic(self.inputs.source_remote,names=[selected['filename']])
        # Require the digest recorded when this exact orbital file was inspected.
        item = dict(next(row for row in location['files'] if row['name'] == selected['filename']))
        item['sha256'] = selected['sha256']
        location = dict(location,files=[item])
        b = OrbitalCubesCalculation.get_builder()
        b.code, b.plot_code, b.cubehandler_code = self.inputs.storage_code,self.inputs.plot_code,self.inputs.cubehandler_code
        b.parameters = orm.Dict(dict=self.ctx.parameters)
        b.orbital_filename = orm.Str(selected['filename'])
        b.orbital_identity = orm.Dict(dict={'kind':kind,'catalog_uuid':str(self.inputs.catalog.uuid),
            'orbital_reference_uuid':str(self.inputs.orbital_reference.uuid),
            'occupation_kind':selected['occupation_kind'], 'levels':selected['levels']})
        attach_source(b,location)
        b.metadata.options = calcjob_options(self.inputs.source_remote,seconds=3600)
        if self.ctx.parameters['retention'] == 'stash':
            from .artifacts import stash_options
            b.metadata.options.stash = stash_options(self.ctx.parameters['stash_directory'],'full_cubes')
        b.metadata.disable_cache = True
        return engine.ToContext(cubes=self.submit(b))

    def inspect(self):
        try:
            validate_cube_outputs(self.ctx.cubes)
        except (OSError,ValueError,KeyError) as exc:
            self.report(str(exc))
            return self.exit_codes.ERROR_CUBES

    def results(self):
        node = orm.load_node(self.ctx.reuse_uuid) if self.ctx.reuse_uuid else self.ctx.cubes
        for name in ('manifest','retrieved','remote_folder','remote_stash'):
            if name in node.outputs:
                self.out(name,node.outputs[name])
