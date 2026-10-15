"""Run the geometry component without the app: python examples/no/run_local.py."""

import json
from pathlib import Path

from aiida import load_profile, orm
from aiida.engine import run_get_node
from ase.io import read

from aiida_empa_orca.workchains import get_builder

load_profile()
structure = orm.StructureData(ase=read(Path(__file__).with_name("no.xyz")))
builder = get_builder(structure, {"charge": 0, "multiplicity": 2}, orm.load_code("orca@localhost"))
builder.metadata.label = "NO doublet PBE/def2-SVP geometry test"
_, node = run_get_node(builder)
print(json.dumps({"uuid": node.uuid, "finished_ok": node.is_finished_ok,
                  "exit_status": node.exit_status, "exit_message": node.exit_message}, indent=2))
assert node.is_finished_ok, node.exit_message
print(node.outputs.optimization_summary.get_dict())
