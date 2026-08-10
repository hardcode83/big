import importlib.util
from pathlib import Path


SPEC = importlib.util.spec_from_file_location(
    "validate_provenance_contract",
    Path(__file__).with_name("validate-provenance-contract.py"),
)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)


def test_contract_self_test() -> None:
    module.self_test()


def test_empty_values_are_supported_absence() -> None:
    assert module.validate({}) == []
