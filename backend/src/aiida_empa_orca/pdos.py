"""Submitted native export and compact, provenance-linked orbital character."""
import io
import json
from importlib.resources import files
from pathlib import PurePosixPath

import numpy as np
from aiida import common, engine, orm
from aiida.parsers import Parser

from .dyson import stage, run_code

PROCESS = 'aiida.calculations:empa_orca.orbital_character'


class OrbitalCharacterCalculation(engine.CalcJob):
    @classmethod
    def define(cls, spec):
        super().define(spec)
        for key, typ in {'helper_code': orm.AbstractCode, 'source': orm.Data,
                         'source_remote': orm.RemoteData, 'structure': orm.StructureData,
                         'identity': orm.Dict, 'location': orm.Dict}.items():
            spec.input(key, valid_type=typ)
        spec.input('metadata.options.parser_name', default='empa_orca.orbital_character')
        spec.input('metadata.options.withmpi', default=False)
        spec.output('metadata', valid_type=orm.Dict)
        spec.output('character', valid_type=orm.ArrayData)
        spec.exit_code(310, 'ERROR_CHARACTER', message='Orbital character checks failed; inspect native export and driver logs.')

    def prepare_for_submission(self, folder):
        identity, location = self.inputs.identity.get_dict(), self.inputs.location.get_dict()
        if identity['kind'] not in ('SCF', 'restricted', 'QRO', 'UNO', 'CASSCF'):
            raise ValueError('Unsupported orbital set')
        if self.inputs.source.uuid != location['uuid']:
            raise ValueError('The orbital location and provenance differ')
        computer = self.inputs.code.computer
        if any(self.inputs[key].computer.uuid != computer.uuid for key in ('helper_code', 'source_remote')):
            raise ValueError('Export and analyse on the orbital source computer')
        item = next(row for row in location['files'] if row['name'] == identity['filename'])
        if item['name'] not in ('aiida.gbw', 'aiida.qro', 'aiida.uno'):
            raise ValueError('Unsupported orbital filename')
        source = self.inputs.source
        if location['kind'] == 'repository':
            path = 'electronic/' + item['name']
        else:
            base = (PurePosixPath(source.target_basepath) / 'electronic' if location['kind'] == 'stash'
                    else PurePosixPath(source.get_remote_path()))
            path = str(base / item['name'])
        info = common.CalcInfo()
        info.local_copy_list, info.remote_copy_list = [], []
        stage(info, source, dict(location, path=path), 'orbitals.gbw')
        with folder.open('orca.json.conf', 'w') as handle:
            json.dump({'MOCoefficients': True, 'Basisset': True,
                       '1elIntegrals': ['S'], 'JSONFormats': ['json']}, handle)
        with folder.open('request.json', 'w') as handle:
            json.dump({'file': item, 'kind': identity['kind'], 'source_uuid': identity['source_uuid'],
                       'structure_uuid': str(self.inputs.structure.uuid),
                       'memory_kb': self.inputs.metadata.options.max_memory_kb or 8 * 1024**2}, handle)
        with folder.open('orbital_character.py', 'w') as handle:
            handle.write(files('aiida_empa_orca').joinpath('scripts/orbital_character.py').read_text())
        info.codes_info = [run_code(self.inputs.code.uuid, ['orbitals.gbw', '-json'], 'export.log'),
                           run_code(self.inputs.helper_code.uuid, ['orbital_character.py'], 'character.log')]
        info.codes_run_mode = common.CodeRunMode.SERIAL
        info.retrieve_list = ['character.json', 'character.npz', 'export.log', 'character.log']
        return info


def validate_arrays(metadata, arrays):
    n = len(arrays['indices'])
    natoms = len(metadata['atoms'])
    if (metadata.get('schema') != 'orca_orbital_character_v1' or
            n != metadata['n_ao'] * len(metadata['channels']) or
            any(arrays[key].shape != (n,) for key in ('indices', 'spin', 'occupations')) or
            arrays['weights'].shape != (n, natoms, len(metadata['angular'])) or
            arrays['p_tensor'].shape != (n, natoms, 3, 3) or
            any(not np.isfinite(a).all() for a in arrays.values()) or
            np.min(arrays['weights']) < -1e-12 or
            np.max(np.abs(arrays['weights'].sum(axis=(1, 2)) - 1)) > 2e-7):
        raise ValueError('Invalid or incomplete compact orbital partition')
    p = metadata['angular'].index('p')
    if (np.max(np.abs(np.trace(arrays['p_tensor'], axis1=2, axis2=3) - arrays['weights'][:, :, p])) > 2e-7 or
            np.max(metadata['orthonormality_errors']) > 1e-7 or
            any(not np.array_equal(arrays['indices'][arrays['spin'] == spin], np.arange(metadata['n_ao']))
                for spin in range(len(metadata['channels'])))):
        raise ValueError('Directional character or spin/orbital identities are inconsistent')
    if metadata['energy_meaning'] == 'none':
        if 'energies_ev' in arrays:
            raise ValueError('Natural orbitals do not supply a KS-energy DOS')
    elif arrays.get('energies_ev', np.empty(0)).shape != (n,):
        raise ValueError('Missing orbital energy labels')


class OrbitalCharacterParser(Parser):
    def parse(self, **kwargs):
        try:
            repository = self.retrieved.base.repository
            metadata = json.loads(repository.get_object_content('character.json'))
            identity = self.node.inputs.identity.get_dict()
            if (metadata['source_uuid'] != identity['source_uuid'] or metadata['kind'] != identity['kind'] or
                    metadata['structure_uuid'] != str(self.node.inputs.structure.uuid) or
                    metadata['charge'] != identity['charge'] or metadata['multiplicity'] != identity['multiplicity']):
                raise ValueError('Orbital character provenance differs from the request')
            atoms = self.node.inputs.structure.get_ase()
            positions = np.array([a['Coords'] for a in metadata['atoms']])
            if metadata['coordinate_units'] == 'Bohr':
                positions *= .5291772105638411
            elif metadata['coordinate_units'] not in ('Angs', 'Angstrom'):
                raise ValueError('Unknown native geometry units')
            if ([a['ElementNumber'] for a in metadata['atoms']] != atoms.numbers.tolist() or
                    not np.allclose(positions, atoms.positions, atol=1e-7, rtol=0)):
                raise ValueError('The native export changed atom order or geometry')
            expected = next(f for f in self.node.inputs.location.get_dict()['files'] if f['name'] == identity['filename'])
            if expected.get('sha256') and metadata['source_sha256'] != expected['sha256']:
                raise ValueError('The exported orbital-file fingerprint changed')
            with repository.open('character.npz', mode='rb') as handle:
                with np.load(io.BytesIO(handle.read()), allow_pickle=False) as archive:
                    arrays = {key: archive[key] for key in archive.files}
            validate_arrays(metadata, arrays)
            result = orm.ArrayData()
            for key, value in arrays.items():
                result.set_array(key, value)
            self.out('character', result)
            self.out('metadata', orm.Dict(dict=metadata))
        except (KeyError, ValueError, OSError, TypeError) as exc:
            self.logger.error(str(exc))
            return self.exit_codes.ERROR_CHARACTER
