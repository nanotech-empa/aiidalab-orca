"""Independent harmonic molecular spectroscopy, with durable Hessian reuse."""

import hashlib
import json
import re

import numpy as np
from aiida import common, engine, orm
from aiida.parsers import Parser

from .calculation import MolecularCalculation
from .common_orbitals import options, validate_source
from .reference import reference_settings, single_point_parameters
from .parser import reference_summary

PROCESS_TYPE = 'aiida.workflows:empa_orca.vibrations'
OUTPUTS = {'vibrational_data': orm.ArrayData, 'summary': orm.Dict,
           'hessian': orm.SinglefileData, 'retrieved': orm.FolderData}


def frequency_parameters(settings, raman=True):
    parameters = single_point_parameters(settings)
    parameters['input_keywords'] = [k for k in parameters['input_keywords'] if k != 'SP'] + ['AnFreq']
    if raman:
        parameters['input_blocks']['elprop'] = {'Polar': 1}
    return parameters


def signature(structure, settings, code_uuid, raman):
    from aiida.orm.implementation import clean_value
    atoms = structure.get_ase()
    payload = {'schema': 1, 'numbers': atoms.numbers.tolist(), 'positions': atoms.positions.tolist(),
               'parameters': clean_value(frequency_parameters(settings, raman)), 'code_uuid': str(code_uuid)}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, allow_nan=False).encode()).hexdigest()


def compatible(node, structure, settings, code_uuid, raman):
    """An IR+Raman calculation also satisfies an IR-only request."""
    return (signature(node.inputs.structure, node.inputs.settings.get_dict(), node.inputs.code.uuid, False)
            == signature(structure, settings, code_uuid, False)
            and (not raman or node.outputs.summary.get_dict().get('raman', False)))


def optimized_source(structure, settings, code, retrieved):
    """Check actual optimized-geometry provenance without requiring a live WFN."""
    producer = retrieved.creator
    if producer is None or 'remote_folder' not in producer.outputs:
        raise ValueError('The optimized reference has no producing ORCA calculation')
    validate_source(structure, settings, code, retrieved, producer.outputs.remote_folder)
    from .reuse import PROCESS_TYPE as GEOMETRY_PROCESS
    for link in retrieved.base.links.get_incoming(link_type=common.LinkType.RETURN).all():
        source = link.node
        if (source.process_type == GEOMETRY_PROCESS and source.inputs.optimize.value
                and 'structure' in source.outputs and source.outputs.structure.uuid == structure.uuid
                and 'optimization_summary' in source.outputs
                and source.outputs.optimization_summary.get_dict().get('converged')):
            return
    raise ValueError('Select a converged optimized geometry before harmonic spectroscopy')


def hessian_sections(text):
    result, current = {}, None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith('$'):
            current = line[1:]
            result[current] = []
        elif current and line and not line.startswith('#'):
            result[current].append(line)
    return result


def block_matrix(lines, rows, columns):
    """Read ORCA's column-block matrices, retaining their Cartesian ordering."""
    result = np.full((rows, columns), np.nan)
    headings = None
    for line in lines:
        fields = line.split()
        if all(re.fullmatch(r'\d+', field) for field in fields):
            headings = [int(field) for field in fields]
            continue
        if headings is None or len(fields) != len(headings) + 1:
            raise ValueError('Malformed Hessian matrix block')
        result[int(fields[0]), headings] = [float(field.replace('D', 'E')) for field in fields[1:]]
    if not np.isfinite(result).all():
        raise ValueError('Incomplete or nonfinite Hessian matrix')
    return result


def parse_vibrations(text, hessian_text, atoms, raman):
    """Read ORCA values; do not rediagonalize or silently scale frequencies."""
    if 'ORCA TERMINATED NORMALLY' not in text:
        raise ValueError('ORCA did not terminate normally')
    electronic_summary = reference_summary(text)
    sections = hessian_sections(hessian_text)
    size = 3 * len(atoms)
    if int(sections['hessian'][0]) != size:
        raise ValueError('Hessian atom count differs from the input geometry')
    hessian = block_matrix(sections['hessian'][1:], size, size)
    if not np.allclose(hessian, hessian.T, atol=1e-7, rtol=0):
        raise ValueError('The Cartesian Hessian is not symmetric')
    if [int(x) for x in sections['normal_modes'][0].split()] != [size, size]:
        raise ValueError('Unexpected normal-mode dimensions')
    normal_modes = block_matrix(sections['normal_modes'][1:], size, size).T.reshape(size, len(atoms), 3)
    frequencies = np.array([float(line.split()[1]) for line in sections['vibrational_frequencies'][1:]])
    if frequencies.shape != (size,):
        raise ValueError('Incomplete frequency list')
    atom_lines = sections['atoms'][1:]
    if [line.split()[0] for line in atom_lines] != atoms.get_chemical_symbols():
        raise ValueError('Hessian atom ordering differs from the input geometry')
    masses = np.array([float(line.split()[1]) for line in atom_lines])
    from ase.units import Bohr
    coordinates = np.array([[float(x) for x in line.split()[2:5]] for line in atom_lines]) * Bohr
    # ORCA centres the Hessian geometry. Translation leaves its Cartesian
    # displacement/response vectors unchanged; never guess a rotation here.
    shift = atoms.positions.mean(axis=0) - coordinates.mean(axis=0)
    if not np.allclose(coordinates + shift, atoms.positions, atol=2e-5, rtol=0):
        raise ValueError('Hessian coordinates differ from the selected optimized geometry')
    linear = np.linalg.matrix_rank(atoms.positions - atoms.positions.mean(axis=0), tol=1e-6) == 1
    first = 5 if linear else 6
    arrays = {'hessian': hessian, 'frequencies': frequencies, 'displacements': normal_modes,
              'masses': masses, 'mode_indices': np.arange(first, size, dtype=int)}
    for section, width, key in [('dipole_derivatives', 3, 'dipole_derivatives'),
                                ('polarizability_derivatives', 6, 'polarizability_derivatives')]:
        lines = sections.get(section)
        if lines:
            values = np.array([[float(x) for x in line.split()] for line in lines[1:]])
            if values.shape != (size, width):
                raise ValueError(f'Unexpected {section} dimensions')
            arrays[key] = values
    ir = np.zeros(size)
    ir_rows = re.findall(r'^\s*(\d+):\s+([-\d.]+)\s+([-\d.Ee+]+)\s+([-\d.Ee+]+)\s+[-\d.Ee+]+\s+\(', text, re.M)
    if not ir_rows:
        raise ValueError('The integrated IR intensity table is missing')
    for mode, frequency, _, intensity in ir_rows:
        index = int(mode)
        if abs(frequencies[index] - float(frequency)) > .02:
            raise ValueError('IR mode frequencies do not match the Hessian')
        ir[index] = float(intensity)
    arrays['ir_intensities'] = ir
    ir_table = np.array([[float(x) for x in line.split()] for line in sections['ir_spectrum'][1:]])
    if ir_table.shape != (size, 6) or not np.allclose(ir_table[:, 2], ir, atol=.011, rtol=0):
        raise ValueError('Stored and printed IR intensities do not agree')
    arrays['ir_intensities'] = ir_table[:, 2]
    arrays['transition_dipoles'] = ir_table[:, 3:6]
    if raman:
        activities, depolarizations = np.zeros(size), np.zeros(size)
        table = text.split('RAMAN SPECTRUM')[-1] if 'RAMAN SPECTRUM' in text else ''
        rows = re.findall(r'^\s*(\d+):\s+([-\d.]+)\s+([-\d.Ee+]+)\s+([-\d.Ee+]+)\s*$', table, re.M)
        if not rows:
            raise ValueError('Requested Raman activities are missing')
        for mode, frequency, activity, depolarization in rows:
            index = int(mode)
            if abs(frequencies[index] - float(frequency)) > .02:
                raise ValueError('Raman mode frequencies do not match the Hessian')
            activities[index], depolarizations[index] = float(activity), float(depolarization)
        arrays.update(raman_activities=activities, depolarizations=depolarizations)
        if 'polarizability_derivatives' not in arrays:
            raise ValueError('Requested polarizability derivatives are missing')
        # ORCA normal-mode vectors have unit Euclidean norm, not unit mass
        # norm. Derivatives are atomic units; convert a0^2 to angstrom^2.
        vectors = normal_modes[first:].reshape(size-first, size)
        mass_norm = np.sqrt(np.sum(vectors**2 * np.repeat(masses, 3), axis=1))
        if np.any(mass_norm <= 0):
            raise ValueError('Zero vibrational displacement vector')
        compact = (vectors / mass_norm[:, None]) @ arrays['polarizability_derivatives'] * Bohr**2
        tensors = np.zeros((size, 3, 3))
        for column, (i, j) in enumerate([(0, 0), (1, 1), (2, 2), (0, 1), (0, 2), (1, 2)]):
            tensors[first:, i, j] = tensors[first:, j, i] = compact[:, column]
        mean = compact[:, :3].mean(axis=1)
        gamma = ((compact[:, 0]-compact[:, 1])**2 + (compact[:, 1]-compact[:, 2])**2
                 + (compact[:, 2]-compact[:, 0])**2 + 6*np.sum(compact[:, 3:]**2, axis=1))/2
        if not np.allclose(45*mean**2 + 7*gamma, activities[first:], atol=2e-5, rtol=2e-5):
            raise ValueError('Raman tensor invariants do not reproduce ORCA activities')
        denominator = 45*mean**2 + 4*gamma
        depol = np.divide(3*gamma, denominator, out=np.zeros_like(gamma), where=denominator > 1e-14)
        if not np.allclose(depol, depolarizations[first:], atol=2e-4, rtol=0):
            raise ValueError('Raman tensor invariants do not reproduce ORCA depolarizations')
        arrays['raman_tensors'] = tensors
    if any(not np.isfinite(value).all() for value in arrays.values()):
        raise ValueError('Nonfinite vibrational data')
    imaginary = [int(i) for i in range(first, size) if frequencies[i] < -20.]
    summary = {'schema_version': 1, 'linear': bool(linear), 'number_of_modes': size - first,
               'scf_summary': electronic_summary,
               'raman': bool(raman), 'imaginary_mode_indices': imaginary,
               'frequency_scaling': float(sections['frequency_scale_factor'][0]),
               'hessian_origin_shift_angstrom': shift.tolist(),
               'units': {'frequencies': 'cm^-1', 'hessian': 'Hartree/bohr^2',
               'displacements': 'Cartesian normal-mode vectors', 'ir_intensities': 'km/mol',
               'raman_activities': 'angstrom^4/amu', 'raman_tensors': 'angstrom^2/sqrt(amu)'},
               'warnings': ['Significant imaginary modes: this geometry is not a verified minimum.'] if imaginary else []}
    return arrays, summary


class VibrationsCalculation(MolecularCalculation):
    _PARSER = 'empa_orca.vibrations'

    @classmethod
    def define(cls, spec):
        super().define(spec)
        spec.input('raman', valid_type=orm.Bool, default=lambda: orm.Bool(True))
        for name, kind in OUTPUTS.items():
            if name != 'retrieved':
                spec.output(name, valid_type=kind)
        spec.exit_code(310, 'ERROR_VIBRATIONS', message='Invalid or incomplete vibrational output; inspect aiida.out and the report.')

    def prepare_for_submission(self, folder):
        info = super().prepare_for_submission(folder)
        info.retrieve_list = ['aiida.out', 'aiida.hess']
        return info


class VibrationsParser(Parser):
    def parse(self, **kwargs):
        try:
            repository = self.retrieved.base.repository
            arrays, summary = parse_vibrations(repository.get_object_content('aiida.out'),
                repository.get_object_content('aiida.hess'), self.node.inputs.structure.get_ase(),
                self.node.inputs.raman.value)
            data = orm.ArrayData()
            for name, values in arrays.items():
                data.set_array(name, values)
            self.out('vibrational_data', data)
            self.out('summary', orm.Dict(dict=summary))
            with repository.open('aiida.hess', mode='rb') as handle:
                self.out('hessian', orm.SinglefileData(file=handle, filename='aiida.hess'))
        except (OSError, ValueError, KeyError, IndexError) as exc:
            self.logger.error(str(exc))
            return self.exit_codes.ERROR_VIBRATIONS


def validate_result(node):
    if node.process_type != PROCESS_TYPE or not node.is_finished_ok:
        raise ValueError('Select a successful vibrational workflow')
    for name, kind in OUTPUTS.items():
        if name not in node.outputs or not isinstance(node.outputs[name], kind):
            raise ValueError(f'Missing {name}')
    with node.outputs.hessian.open(mode='rb') as handle:
        content = handle.read()
    if not content:
        raise ValueError('Stored Hessian is empty')
    arrays, _ = parse_vibrations(node.outputs.retrieved.base.repository.get_object_content('aiida.out'),
        content.decode(), node.inputs.structure.get_ase(), node.outputs.summary.get_dict()['raman'])
    for name, values in arrays.items():
        if not np.array_equal(node.outputs.vibrational_data.get_array(name), values):
            raise ValueError(f'Stored {name} differs from the original ORCA output')


class VibrationsWorkChain(engine.WorkChain):
    @classmethod
    def define(cls, spec):
        super().define(spec)
        spec.input('structure', valid_type=orm.StructureData)
        spec.input('settings', valid_type=orm.Dict)
        spec.input('source_retrieved', valid_type=orm.FolderData)
        spec.input('code', valid_type=orm.AbstractCode)
        spec.input('raman', valid_type=orm.Bool, default=lambda: orm.Bool(True))
        spec.input('reuse_uuid', valid_type=orm.Str, required=False)
        for name, kind in OUTPUTS.items():
            spec.input('reuse.' + name, valid_type=kind, required=False)
            spec.output(name, valid_type=kind)
        spec.outline(cls.setup, engine.if_(cls.needs_calculation)(cls.run_calculation, cls.inspect_calculation), cls.results)
        spec.exit_code(400, 'ERROR_INPUT', message='Invalid vibrational reference; see report.')
        spec.exit_code(401, 'ERROR_CALCULATION', message='ORCA frequency calculation failed.')
        spec.exit_code(402, 'ERROR_REUSE', message='The reviewed vibrational data are unavailable; review a new plan.')

    def setup(self):
        try:
            optimized_source(self.inputs.structure, self.inputs.settings.get_dict(), self.inputs.code, self.inputs.source_retrieved)
            if 'reuse_uuid' in self.inputs:
                previous = orm.load_node(self.inputs.reuse_uuid.value)
                validate_result(previous)
                if not compatible(previous, self.inputs.structure, self.inputs.settings.get_dict(),
                                  self.inputs.code.uuid, self.inputs.raman.value):
                    raise ValueError('The reused calculation has different scientific inputs')
                for name in OUTPUTS:
                    if self.inputs.reuse[name].uuid != previous.outputs[name].uuid:
                        raise ValueError('Reused outputs have different provenance')
        except (ValueError, KeyError, OSError) as exc:
            self.report(str(exc))
            return self.exit_codes.ERROR_REUSE if 'reuse_uuid' in self.inputs else self.exit_codes.ERROR_INPUT

    def needs_calculation(self):
        return 'reuse_uuid' not in self.inputs

    def run_calculation(self):
        settings = reference_settings(self.inputs.settings.get_dict())
        builder = VibrationsCalculation.get_builder()
        builder.structure, builder.code = self.inputs.structure, self.inputs.code
        builder.raman = self.inputs.raman
        builder.parameters = orm.Dict(dict=frequency_parameters(settings, self.inputs.raman.value))
        builder.maxcore_mb = orm.Int(int(.75 * settings['memory_mb'] / settings['nprocs']))
        builder.metadata.options = options(settings)
        # Explicit provenance reuse owns this step; a vanished remote file must
        # never be hidden by an AiiDA cache hit.
        builder.metadata.disable_cache = True
        return engine.ToContext(calculation=self.submit(builder))

    def inspect_calculation(self):
        if not self.ctx.calculation.is_finished_ok:
            return self.exit_codes.ERROR_CALCULATION

    def results(self):
        outputs = self.ctx.calculation.outputs if self.needs_calculation() else self.inputs.reuse
        for name in OUTPUTS:
            self.out(name, outputs[name])
