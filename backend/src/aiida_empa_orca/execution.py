"""Execution backends supported by the single-node ORCA workflows."""


def validate_computer(computer):
    pair = (computer.scheduler_type, computer.transport_type)
    if pair not in (("core.direct", "core.local"), ("core.slurm", "core.ssh")):
        raise ValueError("ORCA requires local/direct execution or Slurm over SSH")
