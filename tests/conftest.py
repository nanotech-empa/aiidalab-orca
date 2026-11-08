import pytest
from aiida import orm

pytest_plugins = ["aiida.tools.pytest_fixtures"]


@pytest.fixture
def configured_orca_tools(aiida_localhost):
    """Explicit mock application runtime for form/submission tests."""
    return orm.InstalledCode(computer=aiida_localhost, filepath_executable='/configured/orca-tools',
                             default_calc_job_plugin='empa_orca.electronic_storage').store()
