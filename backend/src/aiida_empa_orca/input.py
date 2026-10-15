"""Shared ORCA input rendering for submission and the review preview."""

from aiida_orca.utils.input_generator import render_orca_input, render_blocks_after_coordinates


def render_input(parameters, maxcore_mb, coordinate_filename):
    if maxcore_mb < 1:
        raise ValueError("MaxCore must be positive")
    # PostgreSQL JSONB can reorder mapping keys when Dict inputs are reloaded.
    # Render the same order before and after provenance storage.
    parameters = parameters | {"input_blocks": {
        name: dict(sorted(values.items()))
        for name, values in sorted(parameters.get("input_blocks", {}).items())
    }}
    text = f"%maxcore {maxcore_mb}\n{render_orca_input(parameters)}"
    text += "\n%output Print[P_OrbEn] 2 end\n"
    text += f"\n* xyzfile {parameters['charge']} {parameters['multiplicity']} {coordinate_filename}\n"
    after = render_blocks_after_coordinates(parameters)
    return text + (f"\n{after}\n" if after else "")


def preview_input(structure, settings, *, single_point=False):
    from aiida.common.folders import SandboxFolder
    from aiida.orm.implementation import clean_value
    from .calculation import OptimizationCalculation
    from .settings import normalize_settings, orca_parameters

    s = normalize_settings(settings)
    calc = OptimizationCalculation
    # Use the upstream coordinate writer too, including its precision/format.
    with SandboxFolder() as folder:
        calc._write_structure(structure, folder, calc._INPUT_COORDS_FILE)
        with open(folder.get_abs_path(calc._INPUT_COORDS_FILE), encoding="utf8") as stream:
            xyz = stream.read()
    if single_point:
        from .reference import single_point_parameters
        parameters = single_point_parameters(s)
    else:
        parameters = orca_parameters(s)
    return {calc._INPUT_FILE: render_input(clean_value(parameters), int(.75*s["memory_mb"]/s["nprocs"]),
                                         calc._INPUT_COORDS_FILE), calc._INPUT_COORDS_FILE: xyz}
