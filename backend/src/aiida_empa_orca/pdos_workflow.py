"""Default postprocessing for newly computed electronic references only."""
from pathlib import PurePosixPath

from aiida import orm

from .artifacts import resolve_electronic
from .pdos import OrbitalCharacterCalculation
from .rendering import calcjob_options


def available_codes(computer_uuid):
    """Return plain identifiers; helper discovery never retains live Code nodes."""
    found = {'export': [], 'character': []}
    query = orm.QueryBuilder().append(orm.InstalledCode, project='uuid', tag='code').order_by(
        {'code': {'ctime': 'desc'}})
    for uuid in query.all(flat=True):
        code = orm.load_code(uuid)
        if code.computer.uuid != str(computer_uuid) or code.is_hidden:
            continue
        if code.base.extras.get('aiidalab_orca_role', '') == 'orbital_character':
            key = 'character'
        elif PurePosixPath(code.filepath_executable).name == 'orca_2json':
            key = 'export'
        else:
            continue
        found[key].append((f'{code.label}@{code.computer.label}', str(uuid)))
    return found


def analysis_walltime(seconds):
    if type(seconds) is not int or not 60 <= seconds <= 7 * 24 * 3600:
        raise ValueError('Choose an analysis wall time between 1 and 10080 minutes')
    return seconds


def default_plan(computer_uuid, *, enabled=True, memory_gib=8, wallclock_seconds=1800):
    if type(memory_gib) is not int or not 1 <= memory_gib <= 64:
        raise ValueError('Choose an analysis memory budget between 1 and 64 GiB')
    seconds = analysis_walltime(wallclock_seconds)
    found = available_codes(computer_uuid) if enabled else {'export': [], 'character': []}
    export = found['export'][0][1] if found['export'] else None
    helper = found['character'][0][1] if found['character'] else None
    return {'enabled': bool(enabled), 'memory_gib': memory_gib, 'wallclock_seconds': seconds,
            'export_uuid': export, 'helper_uuid': helper,
            'ready': bool(export and helper)}


def configure(builder, plan):
    """Keep postprocessing separate from the electronic-structure settings."""
    builder.character_enabled = orm.Bool(plan['enabled'])
    builder.character_memory_gib = orm.Int(plan['memory_gib'])
    builder.character_wallclock_seconds = orm.Int(analysis_walltime(plan.get('wallclock_seconds', 1800)))
    for option, key in (('character_export_code', 'export_uuid'), ('character_helper_code', 'helper_uuid')):
        if plan.get(key):
            builder[option] = orm.load_code(plan[key])


def character_builder(info, kind, export_uuid, helper_uuid, memory_gib=8, *, wallclock_seconds=1800):
    if kind not in info['sets']:
        raise ValueError('Select an orbital set belonging to this reference')
    if not export_uuid or not helper_uuid:
        raise ValueError('Configure ORCA export and the orbital-character worker on the reference computer')
    if type(memory_gib) is not int or not 1 <= memory_gib <= 64:
        raise ValueError('Choose an analysis memory budget between 1 and 64 GiB')
    seconds = analysis_walltime(wallclock_seconds)
    remote = orm.load_node(info['remote_uuid'])
    filename = info['sets'][kind]
    location = resolve_electronic(remote, names=[filename])
    b = OrbitalCharacterCalculation.get_builder()
    b.code, b.helper_code = orm.load_code(export_uuid), orm.load_code(helper_uuid)
    if any(code.computer.uuid != remote.computer.uuid for code in (b.code, b.helper_code)):
        raise ValueError('Export and analyse on the orbital source computer')
    b.source, b.source_remote = orm.load_node(location['uuid']), remote
    b.structure = orm.load_node(info['structure_uuid'])
    b.identity = orm.Dict(dict={k: info[k] for k in ('source_uuid', 'charge', 'multiplicity')} |
                         {'kind': kind, 'filename': filename})
    b.location = orm.Dict(dict=location)
    b.metadata.options = calcjob_options(remote, seconds=seconds)
    b.metadata.options.max_memory_kb = memory_gib * 1024**2
    b.metadata.label = f'{kind} · Löwdin orbital character and PDOS'
    b.metadata.disable_cache = True
    return b


class OrbitalCharacterMixin:
    """Analysis failures do not discard a valid electronic reference."""
    @classmethod
    def character_spec(cls, spec):
        spec.input('character_enabled', valid_type=orm.Bool, default=lambda: orm.Bool(True))
        spec.input('character_memory_gib', valid_type=orm.Int, default=lambda: orm.Int(8))
        spec.input('character_wallclock_seconds', valid_type=orm.Int, default=lambda: orm.Int(1800),
                   validator=lambda value, _: None if 60 <= value.value <= 604800 else
                   'Analysis wall time must be between 60 and 604800 seconds')
        spec.input('character_export_code', valid_type=orm.AbstractCode, required=False)
        spec.input('character_helper_code', valid_type=orm.AbstractCode, required=False)
        spec.output('pdos_status', valid_type=orm.Dict, required=False)
        for kind in ('scf', 'restricted', 'qro', 'uno', 'casscf'):
            spec.output(f'pdos.{kind}.metadata', valid_type=orm.Dict, required=False)
            spec.output(f'pdos.{kind}.character', valid_type=orm.ArrayData, required=False)

    def run_orbital_character(self):
        self.ctx.pdos_report = {'sets': {}}
        self.ctx.pdos_job_uuids = {}
        if not self.inputs.character_enabled.value:
            self.ctx.pdos_report['state'] = 'disabled'
            return
        if self.ctx.get('reusing') or self.ctx.get('reuse_uuid'):
            self.ctx.pdos_report['state'] = 'reused_reference'
            return
        if 'retrieved' not in self.outputs:
            self.ctx.pdos_report['state'] = 'no_electronic_reference'
            return
        try:
            remote = self.outputs['retrieved'].creator.outputs.remote_folder
            if 'orbital_reference' in self.outputs:
                from .orbital_inspection import variants
                ref = self.outputs['orbital_reference'].get_dict()
                settings = {'charge': ref['charge'], 'multiplicity': ref['source_multiplicity']}
                structure_uuid, sets = str(self.inputs.structure.uuid), variants(ref)
            else:
                settings = self.inputs.settings.get_dict()
                structure_uuid, sets = str(self.outputs['structure'].uuid), {'SCF': 'aiida.gbw'}
            # Old stored process checkpoints may predate this optional input.
            seconds = self.inputs.character_wallclock_seconds.value if 'character_wallclock_seconds' in self.inputs else 1800
            plan = default_plan(remote.computer.uuid, memory_gib=self.inputs.character_memory_gib.value,
                                wallclock_seconds=seconds)
            for option, key in (('character_export_code', 'export_uuid'), ('character_helper_code', 'helper_uuid')):
                if option in self.inputs:
                    plan[key] = str(self.inputs[option].uuid)
            info = {'source_uuid': str(self.node.uuid), 'remote_uuid': str(remote.uuid),
                    'structure_uuid': structure_uuid, 'sets': sets,
                    'charge': settings['charge'], 'multiplicity': settings['multiplicity']}
            for kind in sets:
                try:
                    b = character_builder(info, kind, plan['export_uuid'], plan['helper_uuid'], plan['memory_gib'],
                                          wallclock_seconds=plan['wallclock_seconds'])
                    b.metadata.call_link_label = 'orbital_character_' + kind.lower()
                    job = self.submit(b)
                    self.ctx.pdos_job_uuids[kind] = str(job.uuid)
                    # Engine-owned awaitable, not an ORM object in application state.
                    self.to_context(**{'pdos_wait_' + kind.lower(): job})
                    self.report(f'Computing {kind} orbital character: {job.uuid}')
                except (ValueError, OSError, KeyError, RuntimeError) as exc:
                    self.ctx.pdos_report['sets'][kind] = {'state': 'unavailable', 'message': str(exc)}
                    self.report(f'{kind} PDOS unavailable; electronic results are retained: {exc}')
        except (ValueError, OSError, KeyError, RuntimeError, AttributeError) as exc:
            self.ctx.pdos_report.update(state='unavailable', message=str(exc))
            self.report(f'PDOS unavailable; electronic results are retained: {exc}')

    def inspect_orbital_character(self):
        report = self.ctx.pdos_report
        for kind, uuid in self.ctx.pdos_job_uuids.items():
            # Drop engine awaitable objects after completion, reload operation-locally.
            self.ctx.pop('pdos_wait_' + kind.lower(), None)
            job = orm.load_node(uuid)
            if job.is_finished_ok:
                for key in ('metadata', 'character'):
                    self.out(f'pdos.{kind.lower()}.{key}', job.outputs[key])
                report['sets'][kind] = {'state': 'ready', 'uuid': uuid}
            else:
                message = job.exit_message or f'Analysis ended in {job.process_state.value}'
                report['sets'][kind] = {'state': 'failed', 'uuid': uuid, 'message': message}
                self.report(f'{kind} PDOS failed; electronic results are retained. Retry only the analysis: {message}')
        if 'state' not in report:
            report['state'] = 'ready' if report['sets'] and all(
                row['state'] == 'ready' for row in report['sets'].values()) else 'incomplete'
        # Administrative workflow status; scientific arrays retain their CalcJob creator.
        self.out('pdos_status', orm.Dict(dict=dict(report)).store())
