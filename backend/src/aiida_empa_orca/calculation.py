"""Narrow additions to aiida-orca: MaxCore and durable optimization history."""

from aiida.orm import Dict, Int, TrajectoryData
from aiida_orca.calculations.orca_orca import OrcaCalculation


class OptimizationCalculation(OrcaCalculation):
    _PARSER = "empa_orca.optimization"

    @classmethod
    def define(cls, spec):
        super().define(spec)
        spec.input("maxcore_mb", valid_type=Int)
        spec.output("trajectory", valid_type=TrajectoryData, required=False)
        spec.output("optimization_summary", valid_type=Dict, required=False)
        spec.exit_code(320, "ERROR_NOT_CONVERGED", message="ORCA did not confirm geometry convergence. Inspect the output and optimization limit.")
        spec.exit_code(321, "ERROR_OPTIMIZATION_DATA", message="The optimized coordinates or trajectory are missing or inconsistent.")

    def prepare_for_submission(self, folder):
        info = super().prepare_for_submission(folder)
        info.retrieve_list.append(self._TRAJECTORY_FILE)
        return info

    def _write_input_file(self, parameters, folder, filename):
        from .input import render_input
        content = render_input(parameters.get_dict(), self.inputs.maxcore_mb.value, self._INPUT_COORDS_FILE)
        with open(folder.get_abs_path(filename), "w", encoding="utf8") as handle:
            handle.write(content)
