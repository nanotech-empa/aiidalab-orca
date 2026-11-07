"""Read a restricted, real ORCA FCIDUMP into a portable active-space Hamiltonian.

The native scalar already includes inactive electrons and nuclear repulsion.
Do not add the core energy a second time. No ORCA/QPU execution happens here.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import shutil

import numpy as np
from pyscf import ao2mo
from pyscf.tools import fcidump


class HamiltonianError(ValueError):
    """Unsupported or inconsistent Hamiltonian data."""


def file_sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def assess_native_run(returncode: int, output: str) -> dict:
    """A zero ORCA return code is insufficient: MPI errors may be masked."""
    fatal = any(
        marker in output
        for marker in (
            "ORCA finished by error termination",
            "Segmentation fault",
            "This wavefunction IS NOT FULLY CONVERGED!",
            "ORCA finished with error return",
        )
    )
    normal = "ORCA TERMINATED NORMALLY" in output
    export_only = "Integral dump only" in output
    return {
        "native_returncode": returncode,
        "normal_termination": normal,
        "native_error_diagnostic": fatal,
        "native_run_passed": returncode == 0 and normal and not fatal,
        "integrals_only": export_only,
        "integral_export_marker": "Integrals saved in 'FCIDUMP'." in output,
        "usable_as_converged_state": returncode == 0
        and normal
        and not fatal
        and not export_only,
    }


def electron_sector(norb: int, electrons: int, multiplicity: int) -> tuple[int, int]:
    """Highest-Ms electron counts; fixing Ms alone does not establish total spin."""
    if not all(
        isinstance(x, int) and not isinstance(x, bool)
        for x in (norb, electrons, multiplicity)
    ):
        raise HamiltonianError(
            "Orbital/electron counts and multiplicity must be integers"
        )
    ms2 = multiplicity - 1
    if norb < 1 or multiplicity < 1 or (electrons + ms2) % 2:
        raise HamiltonianError("Invalid electron/spin parity")
    na, nb = (electrons + ms2) // 2, (electrons - ms2) // 2
    if not (0 <= na <= norb and 0 <= nb <= norb):
        raise HamiltonianError("Electron sector exceeds the active orbital space")
    return na, nb


@dataclass(frozen=True)
class ActiveHamiltonian:
    h1: np.ndarray
    eri: np.ndarray
    constant: float
    nelec: tuple[int, int]
    metadata: dict

    @property
    def norb(self) -> int:
        return len(self.h1)

    def save(self, destination: Path) -> None:
        """Create a new bundle; arrays are plain numeric data, never pickled."""
        if destination.exists():
            raise FileExistsError(destination)
        destination.mkdir(parents=True)
        np.savez_compressed(
            destination / "hamiltonian.npz",
            h1=self.h1,
            eri=self.eri,
            constant=np.asarray(self.constant),
            nelec=np.asarray(self.nelec),
        )
        (destination / "metadata.json").write_text(
            json.dumps(self.metadata, indent=2) + "\n"
        )


def read_orca_fcidump(
    path: Path, *, source_identity: dict | None = None, max_tensor_mib: float = 256
) -> ActiveHamiltonian:
    """Validate native restricted FCIDUMP records, then use PySCF's reader.

    Supports the real, spin-free spatial-orbital format emitted by ORCA 6.1.1.
    Unrestricted/spin-orbit/complex variants are intentionally rejected. Missing
    sparse two-electron entries mean zero at the producing export threshold.
    The source input/identity is retained separately; FCIDUMP cannot prove it.
    """
    path = Path(path)
    header_lines, header_done = [], False
    scalar_count, diagonals, seen = 0, set(), {}
    with path.open() as stream:
        for line in stream:
            header_lines.append(line)
            if line.strip().upper() in ("&END", "/"):
                header_done = True
                break
        if not header_done or not header_lines[0].strip().upper().startswith("&FCI"):
            raise HamiltonianError("Missing FCIDUMP header/terminator")
        header = " ".join(header_lines).upper()

        def integer(name):
            values = re.findall(r"\b" + name + r"\s*=\s*([+-]?\d+)", header)
            if len(values) != 1:
                raise HamiltonianError("Missing/ambiguous header field: " + name)
            return int(values[0])

        norb, electrons, ms2 = integer("NORB"), integer("NELEC"), integer("MS2")
        if norb < 1 or norb**4 * 8 > max_tensor_mib * 2**20:
            raise HamiltonianError(
                "Dense integral tensor exceeds the explicit memory limit"
            )
        if ms2 < 0:
            raise HamiltonianError("This adapter expects a highest-Ms sector")
        nelec = electron_sector(norb, electrons, ms2 + 1)
        for flag in ("IUHF", "UHF", "IGENERAL", "ITGENERAL"):
            if re.search(r"\b" + flag + r"\s*=\s*(?:[1-9]|\.TRUE\.|TRUE)", header):
                raise HamiltonianError("Unsupported FCIDUMP variant: " + flag)
        for line_no, line in enumerate(stream, len(header_lines) + 1):
            if not line.strip():
                continue
            fields = line.replace("D", "E").replace("d", "e").split()
            if len(fields) != 5:
                raise HamiltonianError(
                    f"Expected five real integral fields at line {line_no}"
                )
            try:
                value = float(fields[0])
                p, q, r, s = (int(x) for x in fields[1:])
            except ValueError as exc:
                raise HamiltonianError(
                    f"Invalid integral record at line {line_no}"
                ) from exc
            if not np.isfinite(value) or not all(0 <= x <= norb for x in (p, q, r, s)):
                raise HamiltonianError(
                    f"Nonfinite value or invalid index at line {line_no}"
                )
            if (p, q, r, s) == (0, 0, 0, 0):
                scalar_count += 1
                key = ("constant",)
            elif p > 0 and q > 0 and r == s == 0:
                if p == q:
                    diagonals.add(p)
                key = ("h1", *sorted((p, q)))
            elif min(p, q, r, s) > 0:
                pair1, pair2 = sorted((p, q)), sorted((r, s))
                key = ("eri", *sum(sorted((pair1, pair2)), []))
            else:
                raise HamiltonianError(
                    f"Unsupported record convention at line {line_no}"
                )
            if key in seen and abs(seen[key] - value) > 1e-12:
                raise HamiltonianError(
                    f"Conflicting symmetry-equivalent integral at line {line_no}"
                )
            seen[key] = value
    if scalar_count != 1 or diagonals != set(range(1, norb + 1)):
        raise HamiltonianError(
            "Require one explicit core/nuclear scalar and every one-electron diagonal"
        )
    data = fcidump.read(str(path), verbose=False)
    h1 = np.asarray(data["H1"], dtype=float)
    eri = ao2mo.restore(1, data["H2"], norb)
    if h1.shape != (norb, norb) or eri.shape != (norb,) * 4:
        raise HamiltonianError("Unexpected integral shape")
    for array in (h1, eri):
        if not np.isfinite(array).all():
            raise HamiltonianError("Nonfinite parsed integrals")
    if not np.allclose(h1, h1.T, atol=1e-12, rtol=0):
        raise HamiltonianError("One-electron Hamiltonian is not symmetric")
    for other in (
        eri.transpose(1, 0, 2, 3),
        eri.transpose(0, 1, 3, 2),
        eri.transpose(2, 3, 0, 1),
    ):
        if not np.allclose(eri, other, atol=1e-12, rtol=0):
            raise HamiltonianError("Two-electron integral symmetry is inconsistent")
    if source_identity:
        active = source_identity.get("active_orbital_indices")
        if active is not None and (len(active) != norb or len(set(active)) != norb):
            raise HamiltonianError(
                "Source active indices do not match the FCIDUMP dimension"
            )
        expected = source_identity.get("reference_nelec")
        if expected is not None and tuple(expected) != nelec:
            raise HamiltonianError(
                "Source electron/spin identity differs from the FCIDUMP header"
            )
    metadata = {
        "schema_version": 1,
        "format": "real_restricted_active_hamiltonian",
        "energy_unit": "hartree",
        "two_electron_order": "chemist: eri[p,q,r,s]=(pq|rs)",
        "constant_meaning": "native inactive-core plus nuclear energy; add exactly once",
        "reference_nelec": list(nelec),
        "reference_ms2": ms2,
        "norb": norb,
        "spin_orbital_order_for_sampling": "alpha spatial indices ascending, then beta ascending; record qubit/classical-bit layout separately",
        "spin_note": "Fixed N_alpha/N_beta sets Ms, not total S; validate total spin for every solved state",
        "source_fcidump": {"path": str(path.resolve()), "sha256": file_sha256(path)},
        "source_identity": source_identity or {},
        "source_identity_verified_by_fcidump_alone": False,
    }
    h1.setflags(write=False)
    eri.setflags(write=False)
    return ActiveHamiltonian(h1, eri, float(data["ECORE"]), nelec, metadata)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fcidump", type=Path)
    parser.add_argument("--source-identity", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    identity = (
        json.loads(args.source_identity.read_text()) if args.source_identity else None
    )
    hamiltonian = read_orca_fcidump(args.fcidump, source_identity=identity)
    hamiltonian.save(args.output)
    shutil.copy2(args.fcidump, args.output / "FCIDUMP")
    print(
        json.dumps(
            {
                "norb": hamiltonian.norb,
                "nelec": hamiltonian.nelec,
                "constant_hartree": hamiltonian.constant,
                "bundle": str(args.output),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
