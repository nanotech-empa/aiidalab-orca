"""Persistent serial orchestration of independently reviewed CASCI sectors."""
from aiida import engine, orm

from . import casci

PROCESS_TYPE = 'aiida.workflows:empa_orca.casci_batch'
SHARED_INPUTS = ('orbital_reference', 'source_remote', 'active_space', 'code',
                 'storage_code', 'storage_policy', 'native_output_policy', 'force_recompute')


class CasciBatchWorkChain(engine.WorkChain):
    @classmethod
    def define(cls, spec):
        super().define(spec)
        spec.expose_inputs(casci.CasciWorkChain, include=SHARED_INPUTS)
        spec.input('requests', valid_type=orm.List)
        spec.output('report', valid_type=orm.Dict)
        spec.outline(cls.setup, engine.while_(cls.has_next)(cls.run_next, cls.inspect_sector), cls.results)
        spec.exit_code(400, 'ERROR_INPUT', message='Invalid reviewed CASCI batch; no sector was submitted.')
        spec.exit_code(401, 'ERROR_SECTORS', message='One or more sectors failed or were not submitted; inspect the batch report.')

    def setup(self):
        self.ctx.index, self.ctx.current_uuid, self.ctx.stopped = 0, None, False
        self.ctx.rows = []
        try:
            ref = casci.validate_reference(self.inputs.orbital_reference, self.inputs.source_remote)
            space = casci.active_space(self.inputs.active_space.get_dict(), ref)
            requests = self.inputs.requests.get_list()
            if not requests:
                raise ValueError('Review at least one charge/spin sector')
            seen = set()
            for request in requests:
                settings = casci.casci_settings(request['settings'], ref, space)
                pair = (settings['charge'], settings['multiplicity'])
                if pair in seen or request['action'] not in ('compute', 'reuse', 'running'):
                    raise ValueError('Duplicate or unsupported batch sector')
                seen.add(pair)
                if request['action'] != 'compute':
                    node = orm.load_node(request['uuid'])
                    expected = casci.signature(self.inputs.orbital_reference.uuid, space, settings, self.inputs.code.uuid)
                    actual = casci.signature(node.inputs.orbital_reference.uuid, node.inputs.active_space.get_dict(),
                        casci.casci_settings(node.inputs.settings.get_dict(), ref, space), node.inputs.code.uuid)
                    if node.process_type != casci.PROCESS_TYPE or actual != expected:
                        raise ValueError('Existing sector differs from the reviewed reference, space or model')
                    if request['action'] == 'reuse' and not node.is_terminated:
                        raise ValueError('The reviewed saved sector is still running')
                self.ctx.rows.append({'charge':pair[0], 'multiplicity':pair[1], 'uuid':request.get('uuid'),
                    'state':'queued', 'finished':False, 'success':False, 'message':''})
        except (ValueError, KeyError, OSError, RuntimeError) as exc:
            self.report(str(exc))
            return self.exit_codes.ERROR_INPUT

    def has_next(self):
        return not self.ctx.stopped and self.ctx.index < len(self.ctx.rows)

    def sector_builder(self, request):
        b = casci.CasciWorkChain.get_builder()
        for key in SHARED_INPUTS:
            b[key] = self.inputs[key]
        b.settings = orm.Dict(dict=request['settings'])
        b.metadata.call_link_label = f'sector_{self.ctx.index:04d}'
        s = request['settings']
        b.metadata.label = f'CASCI charge {s["charge"]:+d}, multiplicity {s["multiplicity"]}, {s["nroots"]} roots'
        return b

    def run_next(self):
        request = self.inputs.requests.get_list()[self.ctx.index]
        self.ctx.current_uuid = None
        try:
            # Existing/running sectors are waited on; no replacement is submitted.
            node = (self.submit(self.sector_builder(request)) if request['action'] == 'compute'
                    else orm.load_node(request['uuid']))
            self.ctx.current_uuid = str(node.uuid)
            self.ctx.rows[self.ctx.index].update(uuid=str(node.uuid), state='waiting')
            if not node.is_terminated:
                return engine.ToContext(current_sector=node)
        except Exception as exc:
            # A submission exception can have an uncertain broker outcome. Do not retry
            # or submit later sectors automatically in that case.
            self.ctx.rows[self.ctx.index].update(state='submission failed', finished=True, message=str(exc))
            self.ctx.stopped = True
            self.report(f'Batch stopped after submission error: {exc}')

    def inspect_sector(self):
        if not self.ctx.current_uuid:
            return
        node = orm.load_node(self.ctx.current_uuid)
        if not node.is_terminated:
            raise RuntimeError('Cannot advance a CASCI batch before the current sector terminates')
        action = self.inputs.requests.get_list()[self.ctx.index]['action']
        self.ctx.rows[self.ctx.index].update(state='reused' if action == 'reuse' and node.is_finished_ok else 'failed' if node.is_failed else node.process_state.value,
            finished=True, success=node.is_finished_ok,
            message=node.exit_message or ('' if node.is_finished_ok else 'Sector failed; inspect its report'))
        self.ctx.pop('current_sector', None)
        self.ctx.current_uuid = None
        self.ctx.index += 1
        # A failed/excepted/killed child is terminal too: retain its diagnostics,
        # then process the next independent sector without overlapping jobs.

    def results(self):
        rows = [dict(row) for row in self.ctx.rows]
        for row in rows:
            if not row['finished']:
                row.update(state='not submitted', finished=True, message='Batch stopped after a submission error')
        self.out('report', orm.Dict(dict={'sectors':rows, 'sequential':True}).store())
        if any(not row['success'] for row in rows):
            return self.exit_codes.ERROR_SECTORS
