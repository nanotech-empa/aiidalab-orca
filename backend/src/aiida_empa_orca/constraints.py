"""Structured ORCA geometry constraints; stored atom indices are zero-based."""

from math import isfinite

KINDS = {"cartesian": None, "distance": 2, "angle": 3, "dihedral": 4}


def normalize_constraints(values):
    """Validate and canonicalize constraints without changing their meaning."""
    from aiida.orm.implementation import clean_value

    if not isinstance(values, list):
        raise ValueError("Constraints must be a list")
    frozen, internals = {}, {}
    for item in values:
        if not isinstance(item, dict) or set(item) - {"kind", "atoms", "components", "value"}:
            raise ValueError("Each constraint requires a kind and atom indices")
        kind, atoms = item.get("kind"), item.get("atoms")
        if not isinstance(kind, str) or kind not in KINDS:
            raise ValueError("Choose Cartesian, distance, angle or dihedral constraints")
        if not isinstance(atoms, list) or not atoms or any(type(i) is not int or i < 0 for i in atoms):
            raise ValueError("Constraint atom indices must be non-negative integers")
        if len(set(atoms)) != len(atoms):
            raise ValueError("A constraint cannot repeat an atom")
        if kind == "cartesian":
            axes = item.get("components", "xyz")
            if not isinstance(axes, str) or not axes or set(axes) - set("xyz"):
                raise ValueError("Frozen Cartesian components must be x, y and/or z")
            if "value" in item:
                raise ValueError("Cartesian constraints always keep the starting coordinates")
            for atom in atoms:
                frozen.setdefault(atom, set()).update(axes)
        else:
            if len(atoms) != KINDS[kind] or "components" in item:
                raise ValueError(f"A {kind} constraint requires {KINDS[kind]} distinct atoms")
            # Reversing all indices describes the same distance/angle/torsion.
            indices = min(tuple(atoms), tuple(reversed(atoms)))
            key = (kind, indices)
            if key in internals:
                raise ValueError(f"Repeated {kind} constraint on atoms {' '.join(str(i+1) for i in indices)}")
            result = {"kind": kind, "atoms": list(indices)}
            if "value" in item:
                value = item["value"]
                if type(value) not in (int, float) or not isfinite(value):
                    raise ValueError("Constraint targets must be finite numbers")
                if kind == "distance" and value <= 0:
                    raise ValueError("A constrained distance must be positive (angstrom)")
                if kind == "angle" and not 0 < value < 180:
                    raise ValueError("A constrained angle must be between 0 and 180 degrees (exclusive)")
                if kind == "dihedral" and not -180 <= value <= 180:
                    raise ValueError("A constrained dihedral must be between -180 and 180 degrees")
                result["value"] = clean_value(float(value))
            internals[key] = result
    return ([{"kind": "cartesian", "atoms": [atom],
              "components": "".join(axis for axis in "xyz" if axis in axes)}
             for atom, axes in sorted(frozen.items())]
            + [value for _, value in sorted(internals.items())])


def validate_constraints(atoms, values):
    constraints = normalize_constraints(values)
    for item in constraints:
        if max(item["atoms"]) >= len(atoms):
            raise ValueError(f"Constraint refers to an absent atom; this molecule has atoms 1 to {len(atoms)}")
        if item["kind"] == "dihedral":
            try:
                atoms.get_dihedral(*item["atoms"], mic=False)
            except (ZeroDivisionError, ValueError) as exc:
                raise ValueError("The selected dihedral is undefined for collinear atoms") from exc
    frozen = sum(len(item["components"]) for item in constraints if item["kind"] == "cartesian")
    if constraints and frozen == 3 * len(atoms):
        raise ValueError("All Cartesian coordinates are frozen. Release a coordinate or keep the geometry as is.")
    return constraints


def orca_constraints(values):
    """Render a validated nested Constraints block for the upstream writer."""
    lines = []
    for item in normalize_constraints(values):
        indices = " ".join(str(i) for i in item["atoms"])
        if item["kind"] == "cartesian":
            axes = "C" if item["components"] == "xyz" else item["components"].upper()
            lines.extend(f"{{ {axis} {indices} C }}" for axis in axes)
        else:
            kind = {"distance": "B", "angle": "A", "dihedral": "D"}[item["kind"]]
            target = f" {item['value']}" if "value" in item else ""
            lines.append(f"{{ {kind} {indices}{target} C }}")
    return "\n" + "\n".join(f"    {line}" for line in lines) + "\n  end"


def describe_constraints(values):
    """Human-readable descriptions using the viewer's one-based numbering."""
    lines = []
    for item in normalize_constraints(values):
        indices = "–".join(str(i+1) for i in item["atoms"])
        if item["kind"] == "cartesian":
            lines.append(f"Atom {indices}: freeze {item['components']}")
        else:
            unit = "Å" if item["kind"] == "distance" else "°"
            target = f"{item['value']:g} {unit}" if "value" in item else "starting value"
            lines.append(f"{item['kind'].capitalize()} {indices}: {target}")
    return lines
