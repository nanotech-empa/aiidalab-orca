"""Public Qiskit Fermions SqDRIFT adapter, independent of AiiDA.

Uses IBM/Qiskit Fermions (Apache-2.0). See the official SqDRIFT guide:
https://quantum.cloud.ibm.com/docs/en/addons/qiskit-fermions/guides/sqdrift
The sampling generator and the physical Hamiltonian remain distinct artifacts.
"""

import numpy as np


def grouped_generator(path, remove_diagonal):
    from qiskit_fermions.operators import FermionOperator
    from qiskit_fermions.operators.library import FCIDump
    from qiskit_fermions.operators.terms.grouping import (
        group_terms_by_electronic_structure,
        group_coeff_means,
    )
    from qiskit_fermions.operators.terms.ordering import canonical_order, group_order
    from qiskit_fermions.operators.terms.filtering import filter_diagonal_terms

    dump = FCIDump.from_file(str(path))
    operator = FermionOperator.from_fcidump(dump)
    full_terms = len(operator)
    canon = canonical_order(operator.normal_ordered().simplify(atol=1e-16))
    if (
        group_terms_by_electronic_structure(
            canon, 2 * dump.norb, two_body_physicist_order=False
        )
        is not None
    ):
        raise ValueError("Electronic-structure grouping failed")
    if remove_diagonal:
        filter_diagonal_terms(canon)
    canon = group_order(canon)
    weights = np.asarray(group_coeff_means(canon), dtype=float)
    if not len(weights) or weights.sum() <= 0:
        raise ValueError("No sampling excitations remain")
    return (
        canon,
        weights,
        {
            "unfiltered_fermionic_terms": full_terms,
            "generator_terms": len(canon),
            "generator_groups": len(weights),
            "sampling_lambda_hartree": float(weights.sum()),
            "grouping": "public electronic-structure grouping, chemist ERIs",
            "generation_operator": "occupation-diagonal terms removed"
            if remove_diagonal
            else "full Hamiltonian",
            "original_hamiltonian_modified": False,
            "group_order_and_weights_precomputed": True,
        },
    )


def draw_fermionic(
    canon, weights, norb, nelec, time_value, num_groups, seed, occupation=None
):
    from qiskit_fermions.circuit import FermionicCircuit
    from qiskit_fermions.circuit.library import InitializeModes, Evolution
    from qiskit_fermions.transpiler import FermionicPassManager
    from qiskit_fermions.transpiler.presets import generate_preset_jw_pass_manager
    from qiskit_fermions.transpiler.passes import QDriftTrotterization
    from qiskit_fermions.mappers.library import jordan_wigner
    from qiskit_fermions.transpiler.passes.synthesis.evolution import (
        MapperFnEvolutionSynthesis,
        simplify,
    )

    circuit = FermionicCircuit(2 * norb)
    initializer = (
        InitializeModes.from_hartree_fock(norb, nelec)
        if occupation is None
        else InitializeModes(occupation)
    )
    circuit.append(initializer, circuit.modes)
    circuit.append(Evolution(2 * norb, canon, float(time_value)), circuit.modes)
    manager = generate_preset_jw_pass_manager(
        optimization_level=1, basis_gates=["rz", "sx", "x", "cx"], seed_transpiler=seed
    )
    manager.synthesis.methods["Evolution"] = MapperFnEvolutionSynthesis(
        simplify(jordan_wigner)
    )
    manager.optimization = FermionicPassManager(
        [QDriftTrotterization(num_groups, rng=seed, weights=weights)]
    )
    prepared = manager.run(circuit)
    prepared.metadata = {
        "method": "sqdrift",
        "mode_permutation": list(range(2 * norb)),
        "random_seed": seed,
        "evolution_time": float(time_value),
        "num_groups": num_groups,
    }
    return prepared
