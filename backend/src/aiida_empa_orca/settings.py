"""Explicit, versioned settings for isolated-molecule geometry optimization."""

import hashlib
import json

import numpy as np

DEFAULTS = {
    "schema_version": 1,
    "method": "PBE",
    "basis": "def2-SVP",
    "charge": 0,
    "multiplicity": 2,
    "ri": True,
    "optimization": "NormalOpt",
    "max_geometry_steps": 100,
    "max_scf_steps": 200,
    "nprocs": 2,
    "memory_mb": 2048,
    "wallclock_seconds": 1800,
}
METHODS = ("HF", "PBE", "PBE0", "B3LYP", "M062X")
BASES = ("def2-SVP", "def2-TZVP")


def normalize_settings(values):
    """Reject unsupported options instead of silently discarding them."""
    if values.get("schema_version") == 2:
        from .protocols import normalize_v2
        return normalize_v2(values)
    unknown = set(values) - set(DEFAULTS)
    if unknown:
        raise ValueError(f"Unknown settings: {sorted(unknown)}")
    result = DEFAULTS | values
    for key in ("schema_version", "charge", "multiplicity", "max_geometry_steps",
                "max_scf_steps", "nprocs", "memory_mb", "wallclock_seconds"):
        if type(result[key]) is not int:
            raise ValueError(f"{key} must be an integer")
        if key != "charge" and result[key] < 1:
            raise ValueError(f"{key} must be positive")
    if result["schema_version"] != 1:
        raise ValueError("Unsupported settings schema")
    if result["method"] not in METHODS or result["basis"] not in BASES:
        raise ValueError("Unsupported method or basis")
    if result["optimization"] not in ("NormalOpt", "TightOpt"):
        raise ValueError("Choose NormalOpt or TightOpt")
    if type(result["ri"]) is not bool:
        raise ValueError("ri must be a boolean")
    if result["memory_mb"] < 256 * result["nprocs"]:
        raise ValueError("Provide at least 256 MB per process")
    return result


def validate_molecule(structure, settings):
    """Validate molecular coordinates and the requested electron/spin count."""
    atoms = structure.get_ase()
    if any(atoms.pbc):
        raise ValueError("This workflow requires an isolated molecule (no periodic boundaries)")
    if len(atoms) < 2 or not np.isfinite(atoms.positions).all():
        raise ValueError("Provide a molecule with at least two atoms and finite coordinates")
    distances = atoms.get_all_distances()
    if np.any(distances[np.triu_indices(len(atoms), 1)] < 0.1):
        raise ValueError("Overlapping atoms: separation below 0.1 angstrom")
    electrons = int(atoms.numbers.sum()) - settings["charge"]
    unpaired = settings["multiplicity"] - 1
    if electrons < 1 or unpaired > electrons or (electrons - unpaired) % 2:
        raise ValueError(f"Charge and multiplicity are incompatible with {electrons} electrons")
    absent = set(settings.get("element_settings", {})) - set(atoms.get_chemical_symbols())
    if absent:
        raise ValueError(f"Basis/ECP overrides refer to elements absent from this molecule: {sorted(absent)}")


def orca_parameters(settings):
    """Build reviewed HF/DFT input; no implicit method or spin guessing."""
    s = normalize_settings(settings)
    if s["schema_version"] == 2:
        from .protocols import parameters_v2
        return parameters_v2(s)
    spin = ("U" if s["multiplicity"] > 1 else "R") + ("HF" if s["method"] == "HF" else "KS")
    keywords = [s["method"], s["basis"], spin, "Opt", s["optimization"], "TightSCF"]
    keywords += (["RI" if s["method"] == "PBE" else "RIJCOSX", "def2/J"] if s["ri"] else ["NoRI"])
    return {
        "charge": s["charge"], "multiplicity": s["multiplicity"],
        "input_keywords": keywords,
        "input_blocks": {
            "pal": {"nprocs": s["nprocs"]},
            "geom": {"MaxIter": s["max_geometry_steps"]},
            "scf": {"MaxIter": s["max_scf_steps"]},
        },
    }


def signature(structure, settings, code_uuid):
    """Compare effective inputs, not the name of the originating protocol."""
    from aiida.orm.implementation import clean_value
    atoms = structure.get_ase()
    s = normalize_settings(settings)
    payload = {"numbers": atoms.numbers.tolist(), "positions": atoms.positions.tolist(),
               "parameters": clean_value(orca_parameters(s)),
               "resources": {k: s[k] for k in ("nprocs", "memory_mb", "wallclock_seconds")},
               "code_uuid": str(code_uuid)}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, allow_nan=False).encode()).hexdigest()
