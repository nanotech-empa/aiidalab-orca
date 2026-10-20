"""CoPc 2p multiplets: valence SA-CASSCF and frozen-orbital RAS-CI/SOC.

Protocol source: Carniato et al., ChemRxiv 2026-t0g71, SI sections 4–5.
This is an explicit multireference model; XES-based relative intensities are
an approximation to XPS. No continuum photoelectron is calculated.
"""
import itertools
import math
import re

from aiida import common, engine, orm
from aiida.parsers import Parser
from aiida_orca.calculations.orca_orca import OrcaCalculation

from .common_orbitals import copy_orbital, source_spec
from .input import render_input

VALENCE_PROCESS = 'aiida.workflows:empa_orca.cobalt_valence'
SPECTRUM_PROCESS = 'aiida.workflows:empa_orca.cobalt_xps'
CALC_PROCESS = 'aiida.calculations:empa_orca.cobalt_states'
LEGACY_PROTOCOL = 'copc_rasci_soc_core_transition_v1'
PROTOCOL = 'copc_rasci_soc_core_transition_v2'
HARTREE_TO_EV = 27.211386245988


def model_settings(values=None):
    defaults = {'protocol': PROTOCOL, 'nprocs': 8, 'memory_mb': 12288, 'wallclock_seconds': 14400,
                'basis': 'cc-pVTZ', 'cobalt_basis': 'cc-pwCVTZ', 'auxiliary_basis': 'cc-pVTZ/C',
                'max_macroiterations': 100, 'cosx_grid': 3}
    values = dict(values or {})
    if set(values)-set(defaults):
        raise ValueError('Unknown cobalt multiplet setting')
    s=defaults | values
    if s['protocol'] not in (PROTOCOL, LEGACY_PROTOCOL):
        raise ValueError('Unknown CoPc protocol')
    if s['protocol']==LEGACY_PROTOCOL:
        # Read old provenance without silently upgrading its numerical protocol.
        s['cosx_grid']=values.get('cosx_grid')
        if s['cosx_grid'] is not None:raise ValueError('Legacy CoPc protocol has no fixed COSX grid')
    elif type(s['cosx_grid']) is not int or s['cosx_grid']!=3:
        raise ValueError('The consistent CoPc protocol requires COSX angular grid 3')
    for key in ('basis', 'cobalt_basis', 'auxiliary_basis'):
        if s[key] != defaults[key]:
            raise ValueError('This draft validates the explicit CoPc core/valence basis protocol only')
    for key in ('nprocs', 'memory_mb', 'wallclock_seconds', 'max_macroiterations'):
        if type(s[key]) is not int or s[key]<1:
            raise ValueError(key+' must be a positive integer')
    if s['memory_mb']<256*s['nprocs']:
        raise ValueError('Provide at least 256 MiB per process')
    return s


def integration_protocol(model=None):
    s=model_settings(model)
    if s['protocol']!=PROTOCOL:return None
    return {'scheme':'fixed_cosx_v1','angular_grids':[s['cosx_grid']]*3,
            'radial_accuracy':'orca_default'}


def reference_compatible(reference, model=None):
    """Legacy data remain readable but cannot seed a new spectrum directly."""
    expected=integration_protocol(model)
    return (expected is not None and reference.get('protocol')==PROTOCOL
            and reference.get('integration_protocol')==expected)


def require_consistent_reference(reference, model=None):
    if not reference_compatible(reference,model):
        raise ValueError('Update required: this reference does not use the consistent integration protocol. '
                         'Review "Reconverge reference with consistent grid" to reuse its geometry and saved orbitals.')


def integration_metadata(text,model):
    """Validate generated grids, rather than trusting echoed input keywords."""
    protocol=integration_protocol(model)
    if protocol is None:return {}
    grids=[]
    for marker in re.finditer(r'GRIDX (\d)\s*\n-+\s*\n(.*?)(?=\nGRIDX|Grids setup|\Z)',text,re.S):
        fragment=marker[2]
        angular=re.search(r'AngularGrid\s+\.\.\.\s+(\d+)',fragment)
        radial=re.search(r'IntAcc\s+\.\.\.\s+([\d.]+)',fragment)
        points=re.search(r'Total number of grid points\s+\.\.\.\s+(\d+)',fragment)
        if not all((angular,radial,points)):raise ValueError('Incomplete native COSX grid definitions')
        grids.append({'index':int(marker[1]),'angular':int(angular[1]),
                      'intacc':float(radial[1]),'points':int(points[1])})
    if ([g['index'] for g in grids]!=[1,2,3] or
            [g['angular'] for g in grids]!=protocol['angular_grids'] or
            any(abs(g['intacc']-4.338)>1e-6 or g['points']<=0 for g in grids) or
            len({g['points'] for g in grids})!=1):
        raise ValueError('Native COSX grids do not match the consistent integration protocol')
    return {'integration_protocol':protocol,'generated_cosx_grids':grids}


def model_identity(values):
    """Converged scientific results do not depend on scheduler resource choices."""
    return {k:v for k,v in model_settings(values).items()
            if k not in ('nprocs','memory_mb','wallclock_seconds','max_macroiterations')}


def validated_calculation(node):
    from aiida.orm.implementation import clean_value
    if node.process_type!=CALC_PROCESS or not node.is_finished_ok:
        raise ValueError('Choose a successfully completed native Co calculation')
    stage=node.inputs.stage.value
    text=node.outputs.retrieved.base.repository.get_object_content('aiida.out')
    parent=node.inputs.parent_reference.get_dict() if 'parent_reference' in node.inputs else None
    model=node.inputs.model.get_dict()
    parsed=parse_spectrum(text,parent,model) if stage=='spectrum' else parse_reference(text,stage,parent,model)
    if clean_value(parsed)!=node.outputs.reference.get_dict():
        raise ValueError('Stored Co result differs from the native output')
    return parsed



def validate_copc(structure, settings):
    from collections import Counter
    atoms=structure.get_ase()
    if (any(atoms.pbc) or Counter(atoms.get_chemical_symbols()) != Counter(C=32,H=16,N=8,Co=1)
            or settings['charge'] != 0 or settings['multiplicity'] != 2):
        raise ValueError('Automatic Co 2p active-space preparation currently targets neutral doublet CoPc')
    import numpy as np
    centered=atoms.positions-atoms.positions.mean(axis=0)
    normal=np.linalg.svd(centered)[2][-1]
    if abs(normal[2])<.999 or np.std(centered@normal)>.02:
        raise ValueError('Automatic CoPc active-space selection requires a planar molecule oriented close to the xy plane')
    if any(v.get('ecp','none').lower()!='none' for v in settings.get('element_settings',{}).values()):
        raise ValueError('Co core spectroscopy requires an all-electron basis')


def configuration_space(occupation):
    """Published CoPc RAS references, generated rather than copied as a long list.

    One 1s-hole reference, all 2p-hole/valence configurations, and all
    valence-ionized configurations. This gives 376 triplet / 316 singlet CSFs.
    """
    if (len(occupation)!=6 or any(type(x) is not int or x not in (0,1,2) for x in occupation)
            or sum(occupation)!=9 or occupation.count(1)!=1):
        raise ValueError('The 1s-hole spectator reference needs a dominant doublet valence configuration')
    refs={(1,2,2,2)+tuple(occupation)}
    for valence in itertools.product(range(3),repeat=6):
        if sum(valence)==9:
            for hole in (1,2,3):
                core=[2]*4;core[hole]=1
                refs.add(tuple(core)+valence)
        elif sum(valence)==8:
            refs.add((2,2,2,2)+valence)
    return sorted(refs)


def csf_dimension(configurations, multiplicity):
    twice_spin=multiplicity-1
    count=0
    for config in configurations:
        singles=config.count(1)
        if singles<twice_spin or (singles-twice_spin)%2:
            continue
        k=(singles-twice_spin)//2
        count+=math.comb(singles,k)-(math.comb(singles,k-1) if k else 0)
    return count


def input_text(structure, stage, model, parent=None, core=None):
    s=model_settings(model)
    if s['protocol']!=PROTOCOL:
        raise ValueError('Legacy CoPc protocols are read-only; use the consistent integration protocol for new calculations')
    validate_copc(structure,{'charge':0,'multiplicity':2})
    if stage not in ('avas','valence','spectator','spectrum'):
        raise ValueError('Unknown cobalt stage')
    params={'charge':1 if stage=='spectrum' else 0,'multiplicity':3 if stage=='spectrum' else 2,
        'input_keywords':[s['basis'],s['auxiliary_basis'],'RIJCOSX','SARC/J','TightSCF','MOREAD','NoIter'],
        'input_blocks':{'pal':{'nprocs':s['nprocs']},'basis':{'NewGTO Co':f'"{s["cobalt_basis"]}" end'},
            'rel':{'FiniteNuc':'true'},'method':{'FrozenCore':'FC_NONE',
                'AngularGridX':'3,3,3','IntAccX':'-1,-1,-1'}}}
    text='%moinp "reference.gbw"\n'
    if stage=='avas':
        params['input_keywords']+=['AVAS(Valence-D)']
        text+='%casscf\n nel 7\n norb 5\n mult 2\n nroots 1\n maxiter 1\n TrafoStep RI\n ActOrbs unchanged\nend\n'
    elif stage=='valence':
        # NoIter also forces CAS-CI in ORCA; skip only the preliminary SCF.
        params['input_keywords'].remove('NoIter')
        params['input_blocks']['scf']={'MaxIter':0}
        if parent is None or 'valence_selection' not in parent:
            raise ValueError('Verified five-d plus ligand-pi orbital selection is required')
        if parent.get('stage') not in ('avas','valence'):
            raise ValueError('Choose verified AVAS orbitals or an optimized valence reference for reconvergence')
        # A valence restart already contains the selected active space.
        swaps=parent['valence_selection']['swaps'] if parent['stage']=='avas' else []
        if swaps:
            text+='%scf\n rotate\n'+''.join(f'  {{{i},{j},90,0,0}}\n' for i,j in swaps)+' end\nend\n'
        text+=(f'%casscf\n nel 9\n norb 6\n mult 2,4\n nroots 70,20\n maxiter {s["max_macroiterations"]}\n'
               ' TrafoStep RI\n ShiftUp .5\n ShiftDn .5\n ActOrbs unchanged\nend\n')
    elif stage=='spectator':
        if parent is None or parent['stage']!='valence':
            raise ValueError('A completed state-averaged valence reference is required')
        require_consistent_reference(parent,s)
        # ORCA forces all final representations to unchanged for MaxIter=1
        # (including NoIter). Stop before the first orbital update instead,
        # then permit the natural-orbital finalization and final CAS-CI pass.
        # This is canonicalization only, never an orbital-convergence claim.
        params['input_keywords'].remove('NoIter')
        params['input_blocks']['scf']={'MaxIter':0}
        text+='%casscf\n nel 9\n norb 6\n mult 2\n nroots 1\n maxiter 2\n GTol 1e6\n TrafoStep RI\n ActOrbs NatOrbs\n IntOrbs unchanged\n ExtOrbs unchanged\nend\n'
    else:
        if parent is None or core is None:
            raise ValueError('Verified SA-CASSCF and core identification are required')
        require_consistent_reference(parent,s)
        co=next(i for i,z in enumerate(structure.get_ase().numbers) if z==27)
        rows=[r for r in core['assignments'] if r['atom_index']==co and r.get('spin',0)==0]
        one_s=[r['index'] for r in rows if r.get('shell')=='1s']
        two_p=[r['index'] for r in rows if r.get('shell')=='2p']
        if len(one_s)!=1 or len(two_p)!=3 or any(r['population']<.95 for r in rows):
            raise ValueError('Co 1s and all three Co 2p orbitals must be independently assigned')
        start=137  # (290 electrons - 16 active)/2 for CoPc+.
        swaps=list(zip(one_s+two_p,range(start,start+4)))
        if set(i for i,j in swaps)&set(j for i,j in swaps):
            raise ValueError('Overlapping core/target orbital rotations')
        text+='%scf\n rotate\n'+''.join(f'  {{{i},{j},90,0,0}}\n' for i,j in swaps)+' end\nend\n'
        configs=configuration_space(parent['spectator_occupation'])
        dims=[csf_dimension(configs,m) for m in (3,1)]
        if dims != [376,316]:
            raise ValueError('The CoPc RAS model-space dimensions differ from the protocol')
        text+=(f'%casscf\n nel 16\n norb 10\n mult 3,1\n nroots {dims[0]},{dims[1]}\n maxiter 1\n'
               ' TrafoStep RI\n ActOrbs unchanged\n IntOrbs unchanged\n ExtOrbs unchanged\n refs\n')
        text+=''.join('  { '+' '.join(map(str,c))+' }\n' for c in configs)
        text+=(' end\n rel\n  DoSOC true\n  XESSOC true\n  XASMOs 137\n  DoDTensor false\n end\nend\n')
    text+='%output Print[P_AtPopMO_L] 1 end\n'
    rendered=render_input(params,int(.75*s['memory_mb']/s['nprocs']),'aiida.coords.xyz')
    # Keep all explicit scientific controls after simple keyword processing.
    return rendered.replace('* xyzfile ',text+'* xyzfile ',1)


def verify_natural_finalization(text):
    """Require a frozen CAS-CI pass, active-only rotation and final CI pass.

    A deliberately loose GTol skips optimization in this representation-only
    job. Native control flow, not its convergence banner, establishes that no
    orbital-optimization step was taken. The parent energy is checked separately.
    """
    if (not re.search(r'Active\s+Orbitals\s+\.\.\.\s+natural\b',text)
            or not re.search(r'Internal\s+Orbitals\s+\.\.\.\s+unchanged\b',text)
            or not re.search(r'External\s+Orbitals\s+\.\.\.\s+unchanged\b',text)
            or 'FINALIZING ORBITALS' not in text
            or 'Orbital Update' in text
            or [int(i) for i in re.findall(r'MACRO-ITERATION\s+(\d+):',text)]!=[1,2]):
        raise ValueError('Natural-orbital finalization must rotate only the active representation without orbital optimization')
    energies=[float(v) for v in re.findall(r'E\(CAS\)=\s*([-+\d.Ee]+)',text)]
    if (len(energies)!=2 or not all(math.isfinite(v) for v in energies)
            or abs(energies[1]-energies[0])>1e-7):
        raise ValueError('Natural-orbital finalization changed the frozen CAS energy')
    return energies[1]-energies[0]


def parse_reference(text, stage, parent=None, model=None):
    model=model_settings(model or {'protocol':LEGACY_PROTOCOL})
    if 'ORCA TERMINATED NORMALLY' not in text or 'CI-PROBLEM SOLVED' not in text:
        raise ValueError('The native multireference calculation did not finish successfully')
    numerical=integration_metadata(text,model)
    if stage=='spectator' and model['protocol']==PROTOCOL:
        require_consistent_reference(parent or {},model)
        if numerical['generated_cosx_grids']!=parent.get('generated_cosx_grids'):
            raise ValueError('Generated COSX grids differ from the neutral reference; review reference reconvergence before retrying')
    if stage=='spectator':
        verify_natural_finalization(text)
    nel=re.findall(r'Number of active electrons\s+\.\.\.\s+(\d+)',text)
    norb=re.findall(r'Number of active orbitals\s+\.\.\.\s+(\d+)',text)
    expected=(int(nel[-1]),int(norb[-1])) if stage=='avas' and nel and norb else (9,6)
    if not nel or not norb or (int(nel[-1]),int(norb[-1]))!=expected or expected not in ((7,5),(9,6)):
        raise ValueError('The native active space differs from the requested Co model')
    info={'schema_version':1,'stage':stage,'active_electrons':expected[0],'active_orbitals':expected[1],
          'protocol':model['protocol'],'geometry_mode':'fixed','reference_doi':'10.26434/chemrxiv-2026-t0g71',**numerical}
    if stage=='avas':
        avas=re.findall(r'AVAS orbitals\s*:\s*(\d+)',text)
        if not avas or int(avas[-1])!=expected[1]:
            raise ValueError('Native AVAS dimensions were not confirmed')
        info['valence_selection']=select_valence(text,expected)
    else:
        if stage=='valence' and 'THE CAS-SCF GRADIENT HAS CONVERGED' not in text:
            raise ValueError('Valence SA-CASSCF orbital optimization did not converge')
        blocks=list(re.finditer(r'CAS-SCF STATES FOR BLOCK\s+\d+\s+MULT=\s*(\d+)\s+NROOTS=\s*(\d+)',text))
        counts={int(b[1]):int(b[2]) for b in blocks}
        if counts!=({2:70,4:20} if stage=='valence' else {2:1}):
            raise ValueError('The complete doublet/quartet state average was not computed')
        block=next((b for b in reversed(blocks) if int(b[1])==2),None)
        if block is None:
            raise ValueError('Missing final doublet CASSCF states')
        tail=text[block.end():]
        root=re.search(r'ROOT\s+0\s*:\s*E=\s*([-+\d.Ee]+)\s+Eh',tail)
        if root is None:
            raise ValueError('Missing neutral ground-state energy')
        body=tail[root.end():].split('ROOT')[0]
        configs=re.findall(r'([\d.]+)\s+\[\s*\d+\s*\]\s*:\s*([012]{6})',body)
        candidates=[(float(weight),[int(c) for c in occ if c.isdigit()]) for weight,occ in configs]
        selection=select_valence(text,(9,6),pi_index=141,natural=stage=='spectator')
        pi_slot=selection['ligand_pi_orbital']-141
        candidates=[(w,c) for w,c in candidates if len(c)==6 and sum(c)==9 and c.count(1)==1 and c[pi_slot]==2]
        if not candidates:
            raise ValueError('Could not identify the dominant neutral doublet configuration')
        weight,occupation=max(candidates,key=lambda p:p[0])
        if stage=='spectator' and weight<.8:
            raise ValueError('The one-configuration 1s-hole spectator approximation is not adequate for this reference')
        neutral=[]
        for block_start,block_end in zip(blocks,[*blocks[1:],None]):
            fragment=text[block_start.end():block_end.start() if block_end else len(text)]
            first=re.search(r'ROOT\s+0\s*:\s*E=\s*([-+\d.Ee]+)\s+Eh',fragment)
            if first:neutral.append({'multiplicity':int(block_start[1]),'energy_hartree':float(first[1])})
        lowest=min(r['energy_hartree'] for r in neutral)
        info['lowest_neutral_sector_energies']=neutral[-2:]
        info['reference_above_computed_minimum_ev']=(float(root[1])-lowest)*HARTREE_TO_EV
        info.update(ground_energy_hartree=float(root[1]),spectator_occupation=occupation,spectator_weight=weight,
            valence_selection=selection,
            energy_reference='neutral doublet root 0 at the optimized state-averaged orbitals')
        if stage=='spectator':
            if parent is None:
                raise ValueError('Missing state-averaged orbital reference')
            difference=info['ground_energy_hartree']-parent['ground_energy_hartree']
            if abs(difference)>1e-7:
                raise ValueError('Frozen neutral energy differs from the saved SA-CASSCF reference by '
                    f'{difference:.9g} Hartree ({difference*HARTREE_TO_EV:.6g} eV); '
                    'spectrum stopped. Review the neutral reference and reconverge it with the consistent grid before retrying')
            info['active_representation']='state-specific natural orbitals'
            info['orbital_optimization_performed']=False
            info['canonicalization_energy_change_hartree']=verify_natural_finalization(text)
            info['parent_valence_stage']=parent['stage']
            info['reference_above_computed_minimum_ev']=parent['reference_above_computed_minimum_ev']
    return info



def orbital_characters(text):
    if 'LOEWDIN ORBITAL-COMPOSITIONS' not in text:
        raise ValueError('Missing native orbital-character table')
    section=text.split('LOEWDIN ORBITAL-COMPOSITIONS')[-1].split('LOEWDIN REDUCED ACTIVE MOs')[0]
    table={};columns=[]
    for line in section.splitlines():
        if re.fullmatch(r'\s*\d+(?:\s+\d+)+\s*',line):
            columns=[int(x) for x in line.split()]
            for i in columns:table[i]={'co_d':0.,'co_total':0.,'ligand_pz':0.,'ligand_other':0.,'co_s':0.,'co_p':0.}
        m=re.fullmatch(r'\s*(\d+)\s+(Co|C|N|H)\s+(\S+)\s+(.+)',line)
        if not m or not columns:continue
        atom,symbol,angular,values=m.groups();values=[float(v)/100 for v in values.split()]
        if len(values)!=len(columns):raise ValueError('Incomplete native orbital-character table')
        for i,v in zip(columns,values):
            if symbol=='Co':
                table[i]['co_total']+=v
                if angular.startswith('d'):table[i]['co_d']+=v
                if angular=='s':table[i]['co_s']+=v
                if angular.startswith('p'):table[i]['co_p']+=v
            elif symbol in ('C','N'):
                table[i]['ligand_pz' if angular=='pz' else 'ligand_other']+=v
    return table


def select_valence(text, dimensions, *, pi_index=140, natural=False):
    """Verify five metal-d MOs and the highest inactive ligand pi MO.

    AVAS can split a metal d projector over occupied bonding and virtual
    antibonding orbitals (six selected MOs). Retain the five with the largest
    native Co-d weights, and replace the discarded bonding MO by the highest
    inactive ligand pi MO. Fail instead of guessing if the character is mixed.
    This automatic draft accepts an xy-planar molecule; no geometry is rotated.
    """
    table=orbital_characters(text)
    active=list(range(141 if dimensions==(9,6) else 142,147))
    if any(i not in table for i in active) or pi_index not in table:
        raise ValueError('Missing native Co active-orbital populations')
    ranked=sorted(active,key=lambda i:table[i]['co_d'],reverse=True)
    if natural:
        pi_index=max(active,key=lambda i:table[i]['ligand_pz'])
    d=[i for i in active if i!=pi_index] if natural else ranked[:5]
    if min(table[i]['co_d'] for i in d)<.55:
        raise ValueError('Five sufficiently metal-d-like orbitals were not identified')
    if len(ranked)>5 and table[ranked[5]]['co_d']>=min(table[i]['co_d'] for i in d)-.1:
        raise ValueError('Ambiguous bonding/metal-d separation; inspect the orbitals')
    pi=pi_index
    if table[pi]['ligand_pz']<.75 or table[pi]['co_total']>.05:
        raise ValueError('The highest inactive orbital was not verified as a ligand pi orbital (xy-planar CoPc draft)')
    # The five d orbitals must be the contiguous range 142..146. A different
    # ordering requires user-guided active-space selection, not silent guesses.
    if not natural and sorted(d)!=list(range(142,147)):
        raise ValueError('Unexpected Co-d ordering; explicit orbital selection is required')
    return {'d_orbitals':sorted(d),'ligand_pi_orbital':pi,'swaps':[[140,141]] if pi_index==140 else [],
            'native_populations':{str(i):{k:v for k,v in table[i].items() if k not in ('co_s','co_p')} for i in [pi_index]+active},
            'validation':'native Loewdin Co d and ligand pz populations; xy-planar CoPc only'}


class CobaltStatesCalculation(engine.CalcJob):
    @classmethod
    def define(cls,spec):
        super().define(spec)
        spec.input('structure',valid_type=orm.StructureData)
        spec.input('stage',valid_type=orm.Str)
        spec.input('model',valid_type=orm.Dict)
        spec.input('parent_reference',valid_type=orm.Dict,required=False)
        spec.input('core_reference',valid_type=orm.Dict,required=False)
        source_spec(spec)
        spec.input('metadata.options.withmpi',default=False)
        spec.input('metadata.options.output_filename',default='aiida.out')
        spec.input('metadata.options.parser_name',default='empa_orca.cobalt_states')
        spec.output('reference',valid_type=orm.Dict)
        spec.exit_code(310,'ERROR_STATES',message='Co active-space/SOC calculation failed validation; inspect aiida.out.')

    def prepare_for_submission(self,folder):
        text=input_text(self.inputs.structure,self.inputs.stage.value,self.inputs.model.get_dict(),
            self.inputs.parent_reference.get_dict() if 'parent_reference' in self.inputs else None,
            self.inputs.core_reference.get_dict() if 'core_reference' in self.inputs else None)
        with folder.open('aiida.inp','w') as h:h.write(text)
        OrcaCalculation._write_structure(self.inputs.structure,folder,'aiida.coords.xyz')
        info=common.CalcInfo();copy_orbital(info,self.inputs)
        code=common.CodeInfo();code.code_uuid=self.inputs.code.uuid;code.cmdline_params=['aiida.inp']
        code.stdout_name='aiida.out';code.join_files=True
        info.codes_info=[code];info.retrieve_list=['aiida.out','aiida.property.txt']
        return info


class CobaltStatesParser(Parser):
    def parse(self,**kwargs):
        try:
            stage=self.node.inputs.stage.value
            text=self.retrieved.base.repository.get_object_content('aiida.out')
            if stage=='spectrum':
                data=parse_spectrum(text,self.node.inputs.parent_reference.get_dict(),self.node.inputs.model.get_dict())
            else:
                data=parse_reference(text,stage,self.node.inputs.parent_reference.get_dict() if 'parent_reference' in self.node.inputs else None,self.node.inputs.model.get_dict())
            self.out('reference',orm.Dict(dict=data))
        except (ValueError,KeyError,OSError) as exc:
            self.logger.error(str(exc));return self.exit_codes.ERROR_STATES


CM_PER_HARTREE=219474.6313631965


def soc_states(text, *, expected_counts=None):
    """Native absolute SOC energies and the four unrelaxed 1s spectators."""
    expected_counts=expected_counts or {3:376,1:316}
    total_states=sum(m*n for m,n in expected_counts.items())
    matches=list(re.finditer(r'CAS-SCF STATES FOR BLOCK\s+(\d+)\s+MULT=\s*(\d+)\s+NROOTS=\s*(\d+)',text))
    if {int(m[2]):int(m[3]) for m in matches}!=expected_counts:
        raise ValueError('Native RAS-CI did not contain 376 triplets and 316 singlets')
    source_roots=[]
    for m,end in zip(matches,[*matches[1:],None]):
        block=text[m.end():end.start() if end else text.index('CASSCF RELATIVISTIC PROPERTIES',m.end())].split('LOEWDIN ORBITAL-COMPOSITIONS')[0]
        roots=list(re.finditer(r'ROOT\s+(\d+):\s*E=\s*([-+\d.Ee]+)\s+Eh',block))
        found=set()
        for root,stop in zip(roots,[*roots[1:],None]):
            body=block[root.end():stop.start() if stop else len(block)]
            configs=re.findall(r'([\d.]+)\s+(?:\[\s*\d+\s*\]\s*)+:\s*([012]{10})',body)
            if any(float(w)>=.99 and occ[:4]=='1222' for w,occ in configs):
                found.add((int(m[1]),int(root[1])))
        if len(found)!=1:
            raise ValueError('A unique one-configuration 1s spectator was not verified in each spin block')
        source_roots+=sorted(found)
    lowest=re.findall(r'Lowest eigenvalue of the SOC matrix:\s*([-+\d.Ee]+)\s+Eh',text)
    if len(lowest)!=1:raise ValueError('Missing or ambiguous absolute SOC energy reference')
    section=text.split('Eigenvectors:',1)[-1].split('COMPUTING QDPT PROPERTIES')[0]
    markers=list(re.finditer(r'^\s*STATE\s+(\d+):\s*([-+\d.Ee]+)',section,re.M))
    if len(markers)!=total_states or {int(m[1]) for m in markers}!=set(range(total_states)):
        raise ValueError('The complete requested SOC space was not printed')
    states=[]
    for m,end in zip(markers,[*markers[1:],None]):
        body=section[m.end():end.start() if end else len(section)]
        components=re.findall(r'^\s*([\d.]+)\s+[-+\d.Ee]+\s+[-+\d.Ee]+\s*:\s*(\d+)\s+(\d+)\s+\d+\s+[-+\d]+',body,re.M)
        character=sum(float(w) for w,b,r in components if (int(b),int(r)) in source_roots)
        states.append({'index':int(m[1]),'energy_hartree':float(lowest[0])+float(m[2])/CM_PER_HARTREE,
                       'relative_energy_cm1':float(m[2]),'spectator_character':character})
    spectators=[r['index'] for r in states if r['spectator_character']>=.99]
    if len(spectators)!=4:raise ValueError('Four spin-coupled 1s spectator components were not verified')
    return states,spectators,source_roots


def parse_spectrum(text,parent,model=None):
    model=model_settings(model or {'protocol':parent.get('protocol',LEGACY_PROTOCOL)})
    if 'ORCA TERMINATED NORMALLY' not in text:
        raise ValueError('The native RAS-CI/SOC calculation did not terminate normally')
    numerical=integration_metadata(text,model)
    if model['protocol']==PROTOCOL:
        require_consistent_reference(parent,model)
        if numerical['generated_cosx_grids']!=parent.get('generated_cosx_grids'):
            raise ValueError('Generated COSX grids differ from the neutral reference; spectrum validation stopped')
    counts=[re.findall(r'Number of active '+kind+r'\s+\.\.\.\s+(\d+)',text) for kind in ('electrons','orbitals')]
    total=re.findall(r'Total number of electrons\s+\.\.\.\s+(\d+)',text)
    if any(not v for v in counts) or [int(v[-1]) for v in counts]!=[16,10] or not total or int(total[-1])!=290:
        raise ValueError('The CoPc ion must contain 290 electrons and the RAS(16,10) active space')
    core=orbital_characters(text)
    if (137 not in core or core[137]['co_s']<.95
            or any(i not in core or core[i]['co_p']<.95 for i in (138,139,140))):
        raise ValueError('Actual RAS orbitals were not verified as Co 1s and three Co 2p orbitals')
    states,spectators,source_roots=soc_states(text)
    transitions=xes_transitions(text)
    energies={r['index']:r['energy_hartree'] for r in states}
    contributions={}
    for row in transitions:
        i,f=row['initial_state'],row['final_state']
        if i not in spectators or f not in energies:
            raise ValueError('Unexpected initial/final states in the core-transition table')
        energy=(energies[i]-energies[f])*HARTREE_TO_EV
        if abs(energy-row['emission_energy_ev'])>.002:
            raise ValueError('Native emission energies disagree with the SOC state energies')
        binding=(energies[f]-parent['ground_energy_hartree'])*HARTREE_TO_EV
        if 500<binding<1500:
            contributions[f]=contributions.get(f,0.)+row['dipole_strength']/4
    total=sum(contributions.values())
    if not math.isfinite(total) or total<=0:
        raise ValueError('No finite Co 2p core-transition strength')
    sticks=[{'final_state':i,'binding_energy_ev':(energies[i]-parent['ground_energy_hartree'])*HARTREE_TO_EV,
             'raw_dipole_strength':value,'weight':value/total}
            for i,value in sorted(contributions.items()) if value/total>1e-12]
    return {'schema_version':1,'protocol':model['protocol'],**numerical,'reference_doi':'10.26434/chemrxiv-2026-t0g71',
            'geometry_mode':'fixed','neutral_reference_energy_hartree':parent['ground_energy_hartree'],
            'energy_reference':'neutral doublet root 0, spin-free SA-CASSCF orbitals; neutral SOC not included',
            'soc_state_count':len(states),'spin_free_counts':{'triplet':376,'singlet':316},
            'spectator_soc_states':spectators,'spectator_spin_free_roots':[list(r) for r in source_roots],
            'intensity_model':'Bound 1s-to-2p core-transition approximation to XPS; equal population of the four spin-coupled spectator components (unpolarized neutral doublet and core removal). Native SOC includes spin coupling; no extra multiplicity factors. No continuum photoelectron.',
            'total_raw_dipole_strength':total,'sticks':sticks,'soc_states':states,
            'neutral_configuration_weight':parent['spectator_weight'],
            'spectator_occupation':parent['spectator_occupation'],
            'reference_above_computed_neutral_minimum_ev':parent.get('reference_above_computed_minimum_ev',0.),
            'warnings':['Approximate relative intensities; frozen valence orbitals and a single-configuration spectator.',
                        'Absolute energies need basis, relaxation and correlation assessment before experimental interpretation.']}


def xes_transitions(text):
    """Read the native ORCA electric-dipole XESSOC table."""
    marker=re.search(r'SOC CORRECTED\s+EMISSION SPECTRUM VIA TRANSITION ELECTRIC DIPOLE MOMENTS',text)
    if marker is None:raise ValueError('Missing native electric-dipole XESSOC table')
    section=text[marker.end():].split('CASSCF TIMINGS')[0]
    if 'fosc(D2)' not in section[:1000] or '(eV)' not in section[:1000]:
        raise ValueError('Unrecognized native XESSOC units or transition-strength convention')
    rows=[]
    pattern=r'^\s*(\d+)-\S+\s+->\s*(\d+)-\S+\s+(.+)$'
    for line in section.splitlines():
        m=re.fullmatch(pattern,line)
        if not m:continue
        values=[float(v) for v in m[3].split()]
        if len(values)!=8 or not all(math.isfinite(v) for v in values):
            raise ValueError('Invalid native XESSOC numeric columns')
        energy,cm,wavelength,fosc,d2,dx,dy,dz=values
        # There are eight numeric columns in ORCA 6.1: energy (eV/cm-1),
        # wavelength, fosc, D2, and the three absolute dipole components.
        if energy<=0 or fosc<0:raise ValueError('Invalid emission energy or oscillator strength')
        strength=1.5*fosc/(energy/HARTREE_TO_EV)
        # Native D2 is printed with only five decimals. Recover the more
        # precise strength from its oscillator strength and transition energy.
        if abs(strength-d2)>5.2e-6 or abs(d2-dx*dx-dy*dy-dz*dz)>5.6e-6:
            raise ValueError('Native oscillator/dipole strength columns disagree')
        rows.append({'initial_state':int(m[1]),'final_state':int(m[2]),
                     'emission_energy_ev':energy,'oscillator_strength':fosc,'dipole_strength':strength})
    if not rows:raise ValueError('Empty native XESSOC table')
    if len({(r['initial_state'],r['final_state']) for r in rows})!=len(rows):
        raise ValueError('Duplicate native XESSOC transitions')
    return rows
