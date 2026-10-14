"""Geometry protocol defaults and structured expert settings.

Protocol identifiers are immutable versions, not quality guarantees. The fully
resolved settings are stored on each workflow; the CalcJob records ORCA inputs.
"""

from copy import deepcopy
from importlib.resources import files
import re

import numpy as np
import yaml
from ase.data import atomic_numbers

_DOCUMENT = yaml.safe_load(files("aiida_empa_orca").joinpath("protocols/geometry.yaml").read_text())
DEFAULT_PROTOCOL = _DOCUMENT["default_protocol"]
PROTOCOLS = {name: {"label": entry["label"], "description": entry["description"],
                    "settings": deepcopy(_DOCUMENT["default_inputs"]) | entry["overrides"]}
             for name, entry in _DOCUMENT["protocols"].items()}
REFERENCES = ("auto", "RKS", "UKS", "RHF", "UHF")
APPROXIMATIONS = ("auto", "RI", "RIJCOSX", "NoRI")
SCF_CONVERGENCE = ("NormalSCF", "TightSCF", "VeryTightSCF")
OPTIMIZATION = ("NormalOpt", "TightOpt", "VeryTightOpt")
GRIDS = ("default", "DEFGRID1", "DEFGRID2", "DEFGRID3")
DISPERSION = ("default", "D3BJ", "D4")
# A scalar extension cannot replace controls owned by the geometry procedure or
# introduce file dependencies. Nested/array inputs need dedicated data models.
OWNED = {
    "scf": {"maxiter", "hftyp", "guess", "autostart", "moinp"},
    "geom": {"maxiter"},
    "method": {"method", "functional", "runtyp"},
}


def protocol_settings(name=DEFAULT_PROTOCOL, overrides=None):
    if name not in PROTOCOLS:
        raise ValueError(f"Unknown geometry protocol: {name}")
    return {"schema_version": 2, "protocol": name,
            **deepcopy(PROTOCOLS[name]["settings"]), **deepcopy(overrides or {})}


def _token(value, name):
    # ORCA names such as wB97X-D4, def2/J and 6-31G(d,p) are single tokens.
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_+*/(),.\-]*", value):
        raise ValueError(f"{name} must be one ORCA name, without spaces or input syntax")
    if value.lower() in {"end", "opt", "freq", "numfreq", "sp", "engrad", "moread", "noiter", "autostart"}:
        raise ValueError(f"{name} cannot change the geometry procedure")
    return value


def normalize_v2(values):
    from .settings import DEFAULTS
    name = values.get("protocol", DEFAULT_PROTOCOL)
    base = {k: v for k, v in DEFAULTS.items() if k != "ri"}
    base.update(protocol_settings(name))
    unknown = set(values) - set(base)
    if unknown:
        raise ValueError(f"Unknown settings: {sorted(unknown)}")
    s = base | deepcopy(values)
    for key in ("schema_version", "charge", "multiplicity", "max_geometry_steps",
                "max_scf_steps", "nprocs", "memory_mb", "wallclock_seconds"):
        if type(s[key]) is not int or (key != "charge" and s[key] < 1):
            raise ValueError(f"{key} must be {'an' if key == 'charge' else 'a positive'} integer")
    if s["schema_version"] != 2:
        raise ValueError("Unsupported settings schema")
    if s["memory_mb"] < 256 * s["nprocs"]:
        raise ValueError("Provide at least 256 MB per process")
    for key in ("method", "basis", "auxiliary_basis"):
        s[key] = _token(s[key], key)
    for key, options in (("reference", REFERENCES), ("approximation", APPROXIMATIONS),
                         ("optimization", OPTIMIZATION), ("scf_convergence", SCF_CONVERGENCE),
                         ("grid", GRIDS), ("dispersion", DISPERSION)):
        if s[key] not in options:
            raise ValueError(f"Choose {key} from {', '.join(options)}")
    ref = reference(s)
    if (ref.endswith("HF")) != (s["method"].upper() == "HF"):
        raise ValueError("Use RHF/UHF for HF, and RKS/UKS for a DFT functional")
    if ref.startswith("R") and s["multiplicity"] != 1:
        raise ValueError("RHF/RKS requires multiplicity 1; use an unrestricted reference for this spin")
    elements = s["element_settings"]
    if not isinstance(elements, dict):
        raise ValueError("Element settings must map element symbols to basis/ECP choices")
    for element, choices in elements.items():
        if element not in atomic_numbers or element == "X":
            raise ValueError(f"Unknown element: {element}")
        if not isinstance(choices, dict) or not choices or set(choices) - {"basis", "auxiliary_basis", "ecp"}:
            raise ValueError(f"Invalid basis/ECP settings for {element}")
        for key, value in choices.items():
            _token(value, f"{element} {key}")
    blocks = s["block_parameters"]
    if not isinstance(blocks, dict) or set(blocks) - set(OWNED):
        raise ValueError("Scalar expert parameters support the scf, geom and method blocks")
    normalized = {}
    for block, parameters in sorted(blocks.items()):
        if not isinstance(parameters, dict):
            raise ValueError(f"{block} must contain parameter/value pairs")
        entries = {}
        for key, value in parameters.items():
            if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", key):
                raise ValueError("Parameter names must be ORCA identifiers")
            key = key.lower()
            if key in OWNED[block] or key == "end":
                raise ValueError(f"{block}.{key} is managed by the procedure; use its dedicated control")
            if key in entries:
                raise ValueError(f"Repeated parameter: {block}.{key}")
            if type(value) in (float, int):
                if not np.isfinite(value):
                    raise ValueError(f"{block}.{key} must be finite")
            elif type(value) is bool:
                pass
            elif isinstance(value, str):
                _token(value, f"{block}.{key}")
            else:
                raise ValueError(f"{block}.{key} requires a number, boolean or single ORCA token")
            entries[key] = value
        if entries:
            normalized[block] = dict(sorted(entries.items()))
    s["block_parameters"] = normalized
    approximation(s)  # Require an explicit choice for an unclassified functional.
    return s


def reference(s):
    return (s["reference"] if s["reference"] != "auto" else
            ("U" if s["multiplicity"] > 1 else "R") + ("HF" if s["method"].upper() == "HF" else "KS"))


def approximation(s):
    if s["approximation"] != "auto":
        return s["approximation"]
    if s["block_parameters"].get("method"):
        raise ValueError("Choose the RI approximation explicitly when changing functional parameters")
    method = s["method"].upper()
    if method == "PBE":
        return "RI"
    if method in {"HF", "PBE0", "B3LYP", "M062X"}:
        return "RIJCOSX"
    raise ValueError("Choose the RI approximation explicitly for this custom functional")


def parameters_v2(settings):
    s = normalize_v2(settings)
    keywords = [s["method"], s["basis"], reference(s), "Opt", s["optimization"], s["scf_convergence"]]
    ri = approximation(s)
    keywords += [ri] + ([s["auxiliary_basis"]] if ri != "NoRI" else [])
    keywords += [s[k] for k in ("grid", "dispersion") if s[k] != "default"]
    blocks = {"pal": {"nprocs": s["nprocs"]}, "geom": {"MaxIter": s["max_geometry_steps"]},
              "scf": {"MaxIter": s["max_scf_steps"]}}
    for block, parameters in s["block_parameters"].items():
        blocks.setdefault(block, {}).update({k: str(v).lower() if isinstance(v, bool) else v
                                             for k, v in parameters.items()})
    basis = {}
    for element, choices in sorted(s["element_settings"].items()):
        for field, directive in (("basis", "NewGTO"), ("auxiliary_basis", "NewAuxJGTO"), ("ecp", "NewECP")):
            if field in choices:
                value = choices[field]
                if field == "ecp" and value.lower() == "none":
                    basis[f"DelECP {element}"] = None
                else:
                    basis[f"{directive} {element}"] = f'"{value}" end'
    if basis:
        blocks["basis"] = basis
    return {"charge": s["charge"], "multiplicity": s["multiplicity"],
            "input_keywords": keywords, "input_blocks": blocks}


def editable_settings(values):
    """Read legacy settings into the editor without altering stored records."""
    from .settings import normalize_settings
    s = normalize_settings(values)
    if s["schema_version"] == 2:
        return s
    return normalize_v2(protocol_settings(overrides={k: v for k, v in s.items()
                                                    if k not in {"schema_version", "ri"}}) |
                        {"approximation": "auto" if s["ri"] else "NoRI"})


def protocol_overrides(settings):
    s = editable_settings(settings)
    baseline = PROTOCOLS[s["protocol"]]["settings"]
    return {key: s[key] for key in baseline if s[key] != baseline[key]}
