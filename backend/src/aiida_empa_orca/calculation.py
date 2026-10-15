"""Narrow additions to aiida-orca: MaxCore and durable optimization history."""

from aiida.orm import Dict, Int, TrajectoryData
from aiida_orca.calculations.orca_orca import OrcaCalculation


class MolecularCalculation(OrcaCalculation):
    """Shared reviewed input rendering and per-process memory."""
    @classmethod
    def define(cls, spec):
        super().define(spec)
        spec.input("maxcore_mb", valid_type=Int)

    def _write_input_file(self, parameters, folder, filename):
        from .input import render_input
        content = render_input(parameters.get_dict(), self.inputs.maxcore_mb.value, self._INPUT_COORDS_FILE)
        with open(folder.get_abs_path(filename), "w", encoding="utf8") as handle:
            handle.write(content)


class OptimizationCalculation(MolecularCalculation):
    _PARSER = "empa_orca.optimization"

    @classmethod
    def define(cls, spec):
        super().define(spec)
        spec.output("trajectory", valid_type=TrajectoryData, required=False)
        spec.output("optimization_summary", valid_type=Dict, required=False)
        spec.exit_code(320, "ERROR_NOT_CONVERGED", message="ORCA did not confirm geometry convergence. Inspect the output and optimization limit.")
        spec.exit_code(321, "ERROR_OPTIMIZATION_DATA", message="The optimized coordinates or trajectory are missing or inconsistent.")

    def prepare_for_submission(self, folder):
        info = super().prepare_for_submission(folder)
        info.retrieve_list.append(self._TRAJECTORY_FILE)
        return info


class SinglePointCalculation(MolecularCalculation):
    """Fixed-geometry HF/DFT; large electronic files remain on the computer."""

    _PARSER = "empa_orca.single_point"

    @classmethod
    def define(cls, spec):
        super().define(spec)
        spec.output("reference_summary", valid_type=Dict, required=False)
        spec.exit_code(320, "ERROR_SCF_NOT_CONVERGED", message="ORCA did not confirm SCF convergence.")
        spec.exit_code(321, "ERROR_REFERENCE_DATA", message="The single-point energy is missing or invalid.")

    def prepare_for_submission(self, folder):
        info = super().prepare_for_submission(folder)
        info.retrieve_list = [self._OUTPUT_FILE]
        return info
