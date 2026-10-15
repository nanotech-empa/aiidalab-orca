"""Use upstream parsing, with an explicit optimization convergence contract."""

import re

import ase.io
import numpy as np
from aiida.orm import Dict, TrajectoryData
from aiida_orca.parsers import OrcaBaseParser
from aiida_orca.parsers.cclib.utils import convertor


def optimization_converged(text):
    return "THE OPTIMIZATION HAS CONVERGED" in text and "ORCA TERMINATED NORMALLY" in text


def reference_summary(text):
    """Require a converged last SCF and a finite final total energy."""
    states = re.findall(r"SCF (?:CONVERGED AFTER|NOT CONVERGED)", text)
    if not states or states[-1] != "SCF CONVERGED AFTER" or "ORCA TERMINATED NORMALLY" not in text:
        raise ValueError("SCF convergence was not confirmed")
    energies = re.findall(r"FINAL SINGLE POINT ENERGY\s+([-+\d.Ee]+)", text)
    energy = float(energies[-1]) if energies else float("nan")
    if not np.isfinite(energy):
        raise ValueError("No finite final single-point energy")
    result = {"converged": True, "energy_hartree": energy,
              "energy_ev": convertor(energy, "hartree", "eV")}
    spins = re.findall(r"Expectation value of <S\*\*2>\s*:?\s*([\d.]+)", text)
    if spins:
        result["spin_squared"] = float(spins[-1])
    version = re.search(r"Program Version\s+(\S+)", text)
    if version:
        result["orca_version"] = version.group(1)
    return result


class SinglePointParser(OrcaBaseParser):
    def parse(self, **kwargs):
        status = super().parse(**kwargs)
        if status and status.status:
            return status
        text = self.retrieved.base.repository.get_object_content("aiida.out")
        try:
            summary = reference_summary(text)
        except ValueError as exc:
            self.logger.error("SCF data: %s", exc)
            return (self.exit_codes.ERROR_SCF_NOT_CONVERGED if "convergence" in str(exc)
                    else self.exit_codes.ERROR_REFERENCE_DATA)
        self.out("reference_summary", Dict(dict=summary))
        return status


class OptimizationParser(OrcaBaseParser):
    def parse(self, **kwargs):
        status = super().parse(**kwargs)
        if status and status.status:
            return status
        repository = self.retrieved.base.repository
        text = repository.get_object_content("aiida.out")
        if not optimization_converged(text):
            return self.exit_codes.ERROR_NOT_CONVERGED
        try:
            with repository.open("aiida_trj.xyz") as handle:
                frames = ase.io.read(handle, format="xyz", index=":")
            final = self.outputs["relaxed_structure"].get_ase()
            if not frames or any(list(frame.symbols) != list(final.symbols) for frame in frames):
                raise ValueError("Inconsistent trajectory atom ordering")
            if not np.allclose(frames[-1].positions, final.positions, atol=1e-5):
                raise ValueError("Final trajectory frame differs from optimized geometry")
            trajectory = TrajectoryData()
            trajectory.set_trajectory(
                stepids=np.arange(len(frames)), symbols=final.get_chemical_symbols(),
                positions=np.array([frame.positions for frame in frames]),
            )
            energies = [float(x) for x in re.findall(r"FINAL SINGLE POINT ENERGY\s+(-?\d+\.\d+)", text)]
            if not energies:
                raise ValueError("No final energies")
            summary = {"converged": True, "frame_count": len(frames),
                       "energy_hartree": energies[-1],
                       "energy_ev": convertor(energies[-1], "hartree", "eV"),
                       "scf_evaluation_energies_hartree": energies,
                       "energy_axis": "SCF evaluation (may include final evaluation)",
                       "method_parameters": self.node.inputs.parameters.get_dict()}
            spins = re.findall(r"Expectation value of <S\*\*2>\s*:?\s*([\d.]+)", text)
            if spins:
                summary["spin_squared"] = float(spins[-1])
        except (OSError, KeyError, ValueError, IndexError) as exc:
            self.logger.error("Optimization data: %s", exc)
            return self.exit_codes.ERROR_OPTIMIZATION_DATA
        self.out("trajectory", trajectory)
        self.out("optimization_summary", Dict(dict=summary))
        return status
