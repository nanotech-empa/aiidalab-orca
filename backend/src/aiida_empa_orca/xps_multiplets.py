"""Doublet-reference K-edge spin branches and approximate spin projection."""
from aiida import engine, orm

PROCESS_TYPE = 'aiida.workflows:empa_orca.xps_multiplets'
HARTREE_TO_EV = 27.211386245988


def parse_spin_site(text, core_reference, atom_index, electron_count, ground_energy,
                    initial_multiplicity, spin_channel):
    from .scripts.xps_validation import parse_spin_density
    return parse_spin_density(text, core_reference, atom_index, electron_count,
                              ground_energy, initial_multiplicity, spin_channel)


def projected_pair(high_spin, broken_symmetry):
    """Yamaguchi two-state energy estimate; never claims a projected wavefunction."""
    hs, bs = dict(high_spin), dict(broken_symmetry)
    for key in ('atom_index', 'shell', 'ground_energy_hartree', 'initial_multiplicity'):
        if hs[key] != bs[key]:
            raise ValueError('Spin projection requires the same atom, shell and reference energy')
    if hs['spin_assignment'] != 'triplet_ms1' or bs['spin_assignment'] != 'broken_symmetry_ms0':
        raise ValueError('Expected a doublet-reference triplet and broken-symmetry pair')
    sh, sb = hs['spin_squared'], bs['spin_squared']
    if not 1.8 <= sh <= 2.2 or not .5 <= sb <= 1.5 or sh-sb < .5:
        raise ValueError('Spin diagnostics do not support the two-state singlet/triplet projection model')
    # E_S = E_BS + <S2>_BS / (<S2>_HS - <S2>_BS) * (E_BS - E_HS).
    estimate = bs['ionized_energy_hartree'] + sb/(sh-sb)*(bs['ionized_energy_hartree']-hs['ionized_energy_hartree'])
    return {'schema_version': 1, 'model': 'yamaguchi_two_state_energy_estimate',
        'reference_doi': '10.1016/j.cplett.2019.136617', 'atom_index': hs['atom_index'], 'shell': hs['shell'],
        'triplet_binding_energy_ev': hs['binding_energy_ev'],
        'raw_bs_binding_energy_ev': bs['binding_energy_ev'],
        'singlet_estimate_binding_energy_ev': (estimate-hs['ground_energy_hartree'])*HARTREE_TO_EV,
        'singlet_estimate_energy_hartree': estimate, 'triplet_spin_squared': sh, 'bs_spin_squared': sb,
        'warnings': ['Approximate energy projection under a two-state singlet/triplet model; no spin-pure wavefunction or physical peak intensities are produced.']}


@engine.calcfunction
def estimate_singlet_energy(high_spin, broken_symmetry):
    return orm.Dict(dict=projected_pair(high_spin.get_dict(), broken_symmetry.get_dict()))


class XpsMultipletsWorkChain(engine.WorkChain):
    """Compose reusable alpha/beta ionizations; retain raw and estimated results."""
    @classmethod
    def define(cls, spec):
        super().define(spec)
        from .xps import XpsWorkChain
        spec.expose_inputs(XpsWorkChain, exclude=('spin_channel',))
        spec.output_namespace('sites', dynamic=True, valid_type=orm.Dict)
        spec.output_namespace('diagnostics', dynamic=True, valid_type=orm.Dict)
        spec.output_namespace('multiplets', dynamic=True, valid_type=orm.Dict)
        spec.outline(cls.run_alpha, cls.inspect_alpha, cls.run_beta, cls.collect)
        spec.exit_code(400, 'ERROR_BRANCH', message='A spin branch failed; completed atom calculations remain reusable.')
        spec.exit_code(401, 'ERROR_PROJECTION', message='Raw branches exist, but spin projection is outside its validated domain.')

    def branch(self, spin):
        from .xps import XpsWorkChain
        b=XpsWorkChain.get_builder()
        for key,value in self.exposed_inputs(XpsWorkChain).items():
            b[key]=value
        b.spin_channel=orm.Str(spin)
        b.metadata.call_link_label=spin
        return b

    def run_alpha(self):
        return engine.ToContext(alpha=self.submit(self.branch('alpha')))

    def inspect_alpha(self):
        if 'diagnostics' in self.ctx.alpha.outputs:
            for key,node in self.ctx.alpha.outputs.diagnostics.items():
                self.out('diagnostics.alpha_'+key,node)
        if 'sites' in self.ctx.alpha.outputs:
            for key,node in self.ctx.alpha.outputs.sites.items():
                self.out('sites.alpha_'+key,node)
        if not self.ctx.alpha.is_finished_ok:
            return self.exit_codes.ERROR_BRANCH

    def run_beta(self):
        return engine.ToContext(beta=self.submit(self.branch('beta')))

    def collect(self):
        if 'diagnostics' in self.ctx.beta.outputs:
            for key,node in self.ctx.beta.outputs.diagnostics.items():
                self.out('diagnostics.beta_'+key,node)
        if 'sites' in self.ctx.beta.outputs:
            for key,node in self.ctx.beta.outputs.sites.items():
                self.out('sites.beta_'+key,node)
        if not self.ctx.beta.is_finished_ok:
            return self.exit_codes.ERROR_BRANCH
        try:
            for key,bs in self.ctx.alpha.outputs.sites.items():
                result=estimate_singlet_energy(self.ctx.beta.outputs.sites[key],bs)
                self.out('multiplets.'+key,result)
        except ValueError as exc:
            self.report(str(exc))
            return self.exit_codes.ERROR_PROJECTION
