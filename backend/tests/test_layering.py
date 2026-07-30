"""The dependency rule, enforced instead of hoped for (R6.4).

`sdd/steering/backend-architecture.md`: "un `import` de `sqlalchemy`, `fastapi` o
`pydantic` dentro de `backend/app/<dominio>/domain/` es un error de diseño, no un
estilo — recházalo en review igual que un test que falla."

AST-based on purpose: a text grep would be fooled by the word appearing in a
docstring or a comment, and would miss `from a import b as sqlalchemy`.
"""

import ast
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parents[1] / "app"
FORBIDDEN_IN_DOMAIN = {"fastapi", "sqlalchemy", "pydantic", "pydantic_settings", "redis", "celery"}

# Layers that must not be imported from domain/ either: domain sits at the centre.
FORBIDDEN_APP_LAYERS = {"api", "application", "infrastructure"}


def _domain_modules() -> list[Path]:
    return sorted(APP_ROOT.glob("*/domain/**/*.py"))


def _application_modules() -> list[Path]:
    return sorted(APP_ROOT.glob("*/application/**/*.py"))


def _absolute_module(module_path: Path, node: ast.ImportFrom) -> str | None:
    """Resolve an ImportFrom to a dotted module name, relative imports included.

    `level == 1` stays inside the module's own package and is safe. `level >= 2`
    climbs out of it: `from ..infrastructure import x` written in
    `app/<domain>/domain/foo.py` resolves to `app.<domain>.infrastructure`, an
    outer layer. Skipping every relative import — as this test first did — let that
    escape through unnoticed.
    """
    if node.level == 0:
        return node.module
    package_parts = module_path.relative_to(APP_ROOT).parts[:-1]
    if node.level - 1 > len(package_parts):
        return None
    base = ("app", *package_parts[: len(package_parts) - (node.level - 1)])
    return ".".join([*base, node.module]) if node.module else ".".join(base)


def _imported_roots(module_path: Path, tree: ast.Module) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            resolved = _absolute_module(module_path, node)
            if resolved:
                roots.add(resolved.split(".")[0])
    return roots


def _imported_modules(module_path: Path, tree: ast.Module) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            resolved = _absolute_module(module_path, node)
            if resolved:
                modules.add(resolved)
    return modules


def _dynamic_import_calls(tree: ast.Module) -> set[str]:
    """`importlib.import_module("sqlalchemy")` defeats any AST import check.

    The module name is a runtime string, so it cannot be resolved statically. The
    only reliable rule is that `domain/` has no business importing dynamically at
    all — so the call itself is what gets rejected.
    """
    offenders: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        target = node.func
        name = None
        if isinstance(target, ast.Attribute):
            name = target.attr
        elif isinstance(target, ast.Name):
            name = target.id
        if name in {"import_module", "__import__"}:
            offenders.add(name)
    return offenders


def test_there_are_domain_modules_to_check() -> None:
    # Guards against the whole suite passing because the glob matched nothing.
    assert len(_domain_modules()) > 10


@pytest.mark.parametrize("module_path", _domain_modules(), ids=lambda p: str(p.relative_to(APP_ROOT)))
def test_domain_modules_import_no_framework(module_path: Path) -> None:
    tree = ast.parse(module_path.read_text(encoding="utf-8"))

    offenders = _imported_roots(module_path, tree) & FORBIDDEN_IN_DOMAIN

    assert not offenders, (
        f"{module_path.relative_to(APP_ROOT)} imports {sorted(offenders)}; "
        "domain/ must stay pure Python (steering/backend-architecture.md)"
    )


@pytest.mark.parametrize("module_path", _domain_modules(), ids=lambda p: str(p.relative_to(APP_ROOT)))
def test_domain_modules_do_not_import_outer_layers(module_path: Path) -> None:
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    offenders = set()
    for module in _imported_modules(module_path, tree):
        parts = module.split(".")
        # app.<domain>.<layer>...
        if len(parts) >= 3 and parts[0] == "app" and parts[2] in FORBIDDEN_APP_LAYERS:
            offenders.add(module)

    assert not offenders, (
        f"{module_path.relative_to(APP_ROOT)} imports {sorted(offenders)}; "
        "the dependency rule points inwards: api → application → domain ← infrastructure"
    )


@pytest.mark.parametrize("module_path", _domain_modules(), ids=lambda p: str(p.relative_to(APP_ROOT)))
def test_domain_modules_do_not_import_dynamically(module_path: Path) -> None:
    tree = ast.parse(module_path.read_text(encoding="utf-8"))

    offenders = _dynamic_import_calls(tree)

    assert not offenders, (
        f"{module_path.relative_to(APP_ROOT)} calls {sorted(offenders)}; "
        "a dynamic import cannot be checked statically, so domain/ must not use one"
    )


@pytest.mark.parametrize(
    "module_path", _application_modules(), ids=lambda p: str(p.relative_to(APP_ROOT))
)
def test_application_modules_reach_infrastructure_only_through_ports(module_path: Path) -> None:
    """`api/ → application/ → domain/ ← infrastructure/` — the arrows point inwards.

    A use case receives its ports by constructor; importing a concrete adapter, or
    SQLAlchemy itself, would invert the dependency. That is why the transactional
    boundary goes through the `UnitOfWork` port instead of an `AsyncSession`.
    """
    tree = ast.parse(module_path.read_text(encoding="utf-8"))

    framework = _imported_roots(module_path, tree) & {"sqlalchemy", "fastapi"}
    inwards = {
        module
        for module in _imported_modules(module_path, tree)
        if module.split(".")[:1] == ["app"]
        and len(module.split(".")) >= 3
        and module.split(".")[2] in {"infrastructure", "api"}
    }

    assert not framework, f"{module_path.relative_to(APP_ROOT)} imports {sorted(framework)}"
    assert not inwards, (
        f"{module_path.relative_to(APP_ROOT)} imports {sorted(inwards)}; "
        "application/ depends on domain/ ports, never on a concrete adapter"
    )


def test_there_are_application_modules_to_check() -> None:
    assert _application_modules(), "the glob must match the application layer"


def test_the_checks_actually_catch_the_escapes_they_claim_to() -> None:
    """The enforcement mechanism gets its own test.

    Three escapes previously slipped through and are pinned here so a future
    refactor of this file cannot silently reopen them.
    """
    fake_path = APP_ROOT / "auth" / "domain" / "fake.py"

    aliased = ast.parse("import sqlalchemy.orm as sa")
    assert _imported_roots(fake_path, aliased) & FORBIDDEN_IN_DOMAIN == {"sqlalchemy"}

    nested = ast.parse("def f():\n    import fastapi\n    return fastapi")
    assert _imported_roots(fake_path, nested) & FORBIDDEN_IN_DOMAIN == {"fastapi"}

    # `from ..infrastructure import x` inside app/auth/domain/ → app.auth.infrastructure
    climbing = ast.parse("from ..infrastructure import repositories")
    assert "app.auth.infrastructure" in _imported_modules(fake_path, climbing)

    # A same-package relative import stays legitimate.
    sibling = ast.parse("from .exceptions import AuthDomainError")
    assert "app.auth.domain.exceptions" in _imported_modules(fake_path, sibling)

    dynamic = ast.parse("import importlib\nx = importlib.import_module('sqlalchemy')")
    assert _dynamic_import_calls(dynamic) == {"import_module"}

    builtin_dynamic = ast.parse("x = __import__('sqlalchemy')")
    assert _dynamic_import_calls(builtin_dynamic) == {"__import__"}
