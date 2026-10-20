"""Native NO spin branches and the independently published Co RAS dimensions."""
import json
from pathlib import Path

import pytest
from aiida_empa_orca.xps import parse_site, site_parameters
from aiida_empa_orca.scripts.spin_core import spin_assignments
from aiida_empa_orca.xps_multiplets import projected_pair
from aiida_empa_orca.cobalt_xps import configuration_space, csf_dimension

FILES=Path(__file__).parent/'fixtures'/'xps_spin'
REFERENCE=json.loads((FILES/'reference.json').read_text())
CORE=json.loads((FILES/'no-core.json').read_text())


def native(atom,spin):
    return parse_site((FILES/f'no-{atom}-{spin}.out').read_text(),CORE,atom,15,
        REFERENCE['ground_energy_hartree'],initial_multiplicity=2,spin_channel=spin)


def test_native_no_has_two_independent_core_sets():
    rows,verified,_=spin_assignments((FILES/'no-core.out').read_text(),[7,8])
    assert verified
    assert {(r['atom_index'],r['spin_channel']) for r in rows}=={(0,'alpha'),(0,'beta'),(1,'alpha'),(1,'beta')}
    assert all(r['occupation']==1 and r['population']>.99 for r in rows)


def test_no_raw_determinants_are_not_mislabelled_as_pure_singlets():
    for atom,expected in [(0,(409.862727,410.953891)),(1,(542.517819,542.958040))]:
        hs,bs=native(atom,'beta'),native(atom,'alpha')
        assert hs['electron_counts']==[8.,6.] and bs['electron_counts']==[7.,7.]
        assert hs['spin_assignment']=='triplet_ms1' and bs['spin_assignment']=='broken_symmetry_ms0'
        assert 2<hs['spin_squared']<2.04 and 1<bs['spin_squared']<1.04
        pair=projected_pair(hs,bs)
        assert pair['triplet_binding_energy_ev']==pytest.approx(expected[0],abs=1e-6)
        assert pair['singlet_estimate_binding_energy_ev']==pytest.approx(expected[1],abs=1e-6)
        assert pair['raw_bs_binding_energy_ev']<pair['singlet_estimate_binding_energy_ev']
        assert 'spin_squared' not in pair  # an energy estimate has no projected wavefunction


def test_wrong_spin_channel_and_wrong_atom_are_rejected():
    with pytest.raises(ValueError,match='electron counts'):
        parse_site((FILES/'no-0-alpha.out').read_text(),CORE,0,15,REFERENCE['ground_energy_hartree'],initial_multiplicity=2,spin_channel='beta')
    with pytest.raises(ValueError,match='selected atom'):
        parse_site((FILES/'no-0-alpha.out').read_text(),CORE,1,15,REFERENCE['ground_energy_hartree'],initial_multiplicity=2,spin_channel='alpha')


def test_two_state_projection_rejects_an_incompatible_spin_manifold():
    hs,bs=native(0,'beta'),native(0,'alpha')
    with pytest.raises(ValueError,match='two-state'):
        projected_pair(hs,bs|{'spin_squared':2.0})
    with pytest.raises(ValueError,match='same atom'):
        projected_pair(hs,bs|{'atom_index':1})
    # Exactly 50/50 singlet/triplet broken symmetry: -90=(E_S + -91)/2.
    pair=projected_pair(hs|{'spin_squared':2.,'ionized_energy_hartree':-91.},
                        bs|{'spin_squared':1.,'ionized_energy_hartree':-90.})
    assert pair['singlet_estimate_energy_hartree']==pytest.approx(-89.)


def test_both_native_ionization_commands_keep_the_reference_charge():
    for spin,key in [('alpha','IonizeAlpha'),('beta','IonizeBeta')]:
        p=site_parameters(REFERENCE['settings'],0,spin)
        assert p['charge']==0 and p['multiplicity']==2
        assert p['input_blocks']['scf'][key]==0
        assert ('IonizeBeta' if spin=='alpha' else 'IonizeAlpha') not in p['input_blocks']['scf']


def test_generated_cobalt_references_match_published_model_dimensions():
    configs=configuration_space([2,2,2,2,1,0])
    assert all(sum(c)==16 and sum(c[:4])>=7 for c in configs)
    assert len([c for c in configs if c[0]==1])==1
    assert csf_dimension(configs,3)==376
    assert csf_dimension(configs,1)==316


def test_native_avas_distinguishes_bonding_orbital_from_ligand_pi():
    from aiida_empa_orca.cobalt_xps import parse_reference
    text=(FILES/'copc-avas-excerpt.out').read_text()
    selected=parse_reference(text,'avas')['valence_selection']
    assert selected['d_orbitals']==[142,143,144,145,146]
    assert selected['ligand_pi_orbital']==140
    assert selected['swaps']==[[140,141]]
    assert selected['native_populations']['141']['co_d']<.5
    assert selected['native_populations']['146']['co_d']>.6
    with pytest.raises(ValueError,match='Missing native'):
        parse_reference(text.replace('LOEWDIN ORBITAL-COMPOSITIONS','missing'),'avas')


def test_freeze_release_still_uses_the_requested_core_hole():
    p=site_parameters(REFERENCE['settings'],4,'beta','freeze_release')
    assert 'FreezeAndRelease' in p['input_keywords']
    assert p['input_blocks']['scf']['IonizeBeta']==4
    assert p['input_blocks']['scf']['DoMOM']=='false'
    assert p['charge']==0 and p['multiplicity']==2


def test_cobalt_valence_optimizes_orbitals_but_spectrum_keeps_them_fixed(aiida_profile):
    from aiida import orm
    from ase import Atoms
    from aiida_empa_orca.cobalt_xps import input_text,model_settings,parse_reference
    # Only native input generation is tested: these dummy positions are not a
    # scientific structure or submitted calculation.
    structure=orm.StructureData(ase=Atoms('C32H16CoN8'))
    avas=parse_reference((FILES/'copc-avas-excerpt.out').read_text(),'avas')
    valence=input_text(structure,'valence',model_settings(),avas)
    assert 'NoIter' not in valence
    assert 'MaxIter 0' in valence and 'maxiter 100' in valence
    assert '{140,141,90,0,0}' in valence
    assert 'nroots 70,20' in valence
    spectator=input_text(structure,'spectator',model_settings(),{'stage':'valence'})
    assert 'NoIter' not in spectator and 'MaxIter 0' in spectator
    assert 'maxiter 2' in spectator and 'GTol 1e6' in spectator
    assert 'ActOrbs NatOrbs' in spectator
    assert spectator.index('TightSCF')<spectator.index('GTol 1e6')<spectator.index('* xyzfile')
    core={'assignments':[{'atom_index':48,'spin':0,'shell':shell,'index':i,'population':.999}
                         for i,shell in [(0,'1s'),(2,'2p'),(3,'2p'),(4,'2p')]]}
    spectrum=input_text(structure,'spectrum',model_settings(),{'spectator_occupation':[2,2,2,2,1,0]},core)
    assert 'NoIter' in spectrum and 'maxiter 1' in spectrum
    assert 'nroots 376,316' in spectrum and 'XESSOC true' in spectrum
    assert '{0,137,90,0,0}' in spectrum
    assert 'ActOrbs unchanged' in spectrum and 'IntOrbs unchanged' in spectrum


def test_native_natural_finalization_preserves_energy_without_optimization():
    import re
    from aiida_empa_orca.cobalt_xps import verify_natural_finalization,parse_reference
    unchanged=(FILES/'co-natural-one-pass.out').read_text()
    natural=(FILES/'co-natural-finalization.out').read_text()
    assert 'ORCA TERMINATED NORMALLY' in natural
    verify_natural_finalization(natural)
    with pytest.raises(ValueError,match='without orbital optimization'):
        parse_reference(unchanged,'spectator')
    with pytest.raises(ValueError,match='without orbital optimization'):
        verify_natural_finalization(natural+'\n--- Orbital Update [SuperCI(PT)]\n')
    with pytest.raises(ValueError,match='without orbital optimization'):
        verify_natural_finalization(natural.replace('MACRO-ITERATION   2:','MACRO-ITERATION   3:'))
    changed=re.sub(r'(E\(CAS\)=\s*)-1381\.091420891',r'\g<1>-1381.081420891',natural,count=1)
    with pytest.raises(ValueError,match='changed the frozen CAS energy'):
        verify_natural_finalization(changed)
    # Native fixed-orbital CAS-CI energy before/after the representation change.
    roots=lambda text:[float(v) for v in re.findall(r'ROOT\s+0:\s*E=\s*([-+\d.Ee]+)\s+Eh',text)]
    assert roots(natural)[-1]==pytest.approx(roots(unchanged)[-1],abs=1e-9)
    assert 'Orbital Update' not in natural


def test_native_soc_xes_format_preserves_spin_coupling_and_energy_differences():
    from aiida_empa_orca.cobalt_xps import soc_states,xes_transitions,HARTREE_TO_EV
    text=(FILES/'co-17-state-format.out').read_text()
    # A reduced atomic model checks the native format. It is deliberately not
    # accepted as the production CoPc 376/316-state model.
    with pytest.raises(ValueError,match='376 triplets'):
        soc_states(text)
    states,sources,roots=soc_states(text,expected_counts={3:4,1:5})
    assert sources==[13,14,15,16] and roots==[(0,3),(1,4)]
    assert len(states)==17
    transitions=xes_transitions(text)
    assert len(transitions)==52
    assert {r['initial_state'] for r in transitions}==set(sources)
    energies={r['index']:r['energy_hartree'] for r in states}
    for row in transitions:
        assert abs((energies[row['initial_state']]-energies[row['final_state']])*HARTREE_TO_EV-row['emission_energy_ev'])<.002
        assert row['dipole_strength']>=0
    # Spin-free singlet/triplet blocks are mixed in native SOC final states.
    assert any('1.8A' in l for l in text.splitlines() if '->' in l)
    assert sum(r['dipole_strength'] for r in transitions)/4==pytest.approx(.001917795445,rel=1e-8)
    with pytest.raises(ValueError,match='Missing native'):
        xes_transitions(text.replace('SOC CORRECTED   EMISSION SPECTRUM','removed'))


def test_copc_natural_rotation_passes_but_inconsistent_reference_blocks_spectrum():
    from aiida_empa_orca.cobalt_xps import verify_natural_finalization,parse_reference
    text=(FILES/'copc-natural-excerpt.out').read_text()
    assert abs(verify_natural_finalization(text))<1e-7
    # Real preceding SA-CASSCF result, not an adjusted energy reference.
    parent={'stage':'valence','ground_energy_hartree':-3038.6762444642,
            'reference_above_computed_minimum_ev':.48863789961062204}
    with pytest.raises(ValueError,match='Frozen neutral energy differs from the saved SA-CASSCF reference'):
        parse_reference(text,'spectator',parent)


def test_spin_spectrum_exposes_raw_and_estimated_energies_without_fictitious_intensities():
    from aiidalab_orca.xps import XpsSpectrum
    from aiidalab_orca.app import close_widget_tree
    import numpy as np
    hs,bs=native(0,'beta'),native(0,'alpha')
    sites=[r|{'symbol':'N','label':r['spin_assignment'],'data_uuid':spin} for r,spin in [(hs,'hs'),(bs,'bs')]]
    pair=projected_pair(hs,bs)|{'data_uuid':'projection'}
    widget=XpsSpectrum({'sites':sites,'multiplets':[pair]})
    try:
        assert '410.95' in widget.table.value and 'energy estimate' in widget.table.value
        assert '1.091' not in widget.table.value  # these are absolute BEs, not splitting labels
        widget.spin_view.value='raw'
        assert '410.40' in widget.table.value and '410.95' not in widget.table.value
        for trace in widget.figure.data[:2]:
            assert np.trapezoid(trace.y,trace.x)==pytest.approx(1.,abs=1e-5)
    finally:close_widget_tree(widget)
