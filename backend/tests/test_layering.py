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


# --- Celery is a delivery mechanism, not a layer (`celery-jobs` R1, design D2) ---------

#: The only modules allowed to import Celery. `app/worker.py` owns the app instance and
#: `app/scheduler/` is the delivery layer — the scheduler's equivalent of `api/`. Anywhere
#: else means a task decorator has grown inside a domain, which is how business rules end
#: up depending on a broker.
CELERY_IMPORTERS = {"app/worker.py"}
CELERY_IMPORTER_PREFIX = "app/scheduler/"


def _all_app_modules() -> list[Path]:
    return sorted(APP_ROOT.glob("**/*.py"))


@pytest.mark.parametrize("module_path", _all_app_modules(), ids=lambda p: str(p))
def test_celery_is_imported_only_by_the_worker_and_the_scheduler(module_path: Path) -> None:
    relative = module_path.relative_to(APP_ROOT.parent).as_posix()
    tree = ast.parse(module_path.read_text())
    if "celery" not in _imported_roots(module_path, tree):
        return
    assert (
        relative in CELERY_IMPORTERS or relative.startswith(CELERY_IMPORTER_PREFIX)
    ), f"{relative} imports celery; only app/worker.py and app/scheduler/** may"


@pytest.mark.parametrize("module_path", _all_app_modules(), ids=lambda p: str(p))
def test_the_scheduler_never_reaches_into_a_domains_internals(module_path: Path) -> None:
    """`app/scheduler/` composes use cases and repositories; it must not import a
    `domain/` module's private machinery or bypass `application/` with its own rules.

    Kept deliberately narrow: importing entities, enums and ports is how it wires the use
    cases, so what this bans is the one thing that would make it a second application
    layer — importing another domain's `application` internals under an alias.
    """
    relative = module_path.relative_to(APP_ROOT.parent).as_posix()
    if not relative.startswith(CELERY_IMPORTER_PREFIX):
        return
    tree = ast.parse(module_path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert "._" not in node.module, f"{relative} imports a private module"


# --- the render locale is asked for, not read off the row -------------------------------
# (`frontend-verification-fixes` R1, design D3/D5)

#: The shape banned in `app/*/api/`: a two-attribute chain ending in `.context.
#: preferred_language`. That is how a route reaches the *stored* preference of the user
#: row, and after design D3 the stored preference is the wrong one of the two languages
#: reachable from a router — `RequestLocaleDep` carries the one the request asked for, and
#: it is what a route composing user-facing text must render in.
#:
#: The failure mode this exists to prevent is silent: a new route reads the row, serves
#: Spanish to a reader who set the interface to English, and nothing goes red until
#: somebody looks at a screen.
#:
#: Banning the SHAPE rather than the NAME is what makes a whitelist unnecessary for the
#: four serialisers that legitimately name the column — `auth/api/user_schemas.py`,
#: `auth/api/schemas.py`, `platform/api/schemas.py` and `reservations/api/schemas.py` read
#: it straight off the ORM row (`user.preferred_language`, `guest.preferred_language`), a
#: one-attribute chain that does not match. A `grep` for the name would hit all four.
LOCALE_ATTR = "preferred_language"
LOCALE_OWNER_ATTR = "context"

#: The one site allowed to read the stored preference inside `app/*/api/`, as
#: (module, enclosing function). It is the function that DEFINES the alternative: design D3
#: makes `RequestLocaleDep` resolve `X-Locale` -> the stored row preference -> `es`, so the
#: fallback half of that chain has to read the column exactly once, and this is where.
#:
#: Keyed by enclosing function and not by module, deliberately — the same file also builds
#: `RequestContext` and is where a future reader would most plausibly appear. A second
#: function in `dependencies.py` reading the row still fails, so the exemption cannot widen
#: without this tuple being edited. Same pattern as `CELERY_IMPORTERS` above.
#:
#: Note for review: design D5 says "sin lista blanca", which was written believing
#: `dependencies.py` "la construye pero no la lee así" — true before design D3's dependency
#: was written, and false after, since task 2.1 specifies exactly this read. The shape ban
#: and the file scope D5 asked for are intact; what changed is that the design's own
#: mandated implementation turned out to sit inside the scope it defined.
LOCALE_ROW_READERS = {("app/auth/api/dependencies.py", "get_request_locale")}


def _api_modules() -> list[Path]:
    return sorted(APP_ROOT.glob("*/api/*.py"))


def _stored_locale_reads(tree: ast.Module) -> list[tuple[str | None, int]]:
    """Every `<anything>.context.preferred_language` in `tree`, with its enclosing function.

    The enclosing function is resolved by walking down from the module rather than up from
    the node, because `ast` parents are not linked; a nested `def` reports the innermost
    one, which is the name a reader would have to write to claim the exemption.

    Also catches the one-step-removed shape `ctx = x.context; ctx.preferred_language`: a
    bare `.context` alias is resolved per enclosing function before the attribute walk, so
    binding the owner to a local name first does not exit the ban.
    """
    enclosing: dict[int, str | None] = {}

    def descend(node: ast.AST, function: str | None) -> None:
        for child in ast.iter_child_nodes(node):
            name = (
                child.name
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                else function
            )
            enclosing[id(child)] = name
            descend(child, name)

    enclosing[id(tree)] = None
    descend(tree, None)

    context_aliases: dict[str | None, set[str]] = {}
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Attribute)
            and node.value.attr == LOCALE_OWNER_ATTR
        ):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    context_aliases.setdefault(enclosing[id(node)], set()).add(target.id)

    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute) or node.attr != LOCALE_ATTR:
            continue
        owner = node.value
        function = enclosing[id(node)]
        is_direct_context = isinstance(owner, ast.Attribute) and owner.attr == LOCALE_OWNER_ATTR
        is_aliased_context = isinstance(owner, ast.Name) and owner.id in context_aliases.get(
            function, set()
        )
        if is_direct_context or is_aliased_context:
            found.append((function, node.lineno))
    return found


def test_there_are_api_modules_to_check() -> None:
    # Same reason as `test_there_are_domain_modules_to_check`: a glob that matched nothing
    # would make the guard below pass by doing nothing at all.
    assert len(_api_modules()) > 10, "the glob must match the api layer"


@pytest.mark.parametrize("module_path", _api_modules(), ids=lambda p: str(p))
def test_no_api_module_renders_from_the_stored_language_preference(module_path: Path) -> None:
    """A route composes text in the language the REQUEST asked for (`RequestLocaleDep`),
    never in the one stored on the user row (`RequestContext.preferred_language`)."""
    relative = module_path.relative_to(APP_ROOT.parent).as_posix()
    tree = ast.parse(module_path.read_text(encoding="utf-8"))

    for function, lineno in _stored_locale_reads(tree):
        assert (relative, function) in LOCALE_ROW_READERS, (
            f"{relative}:{lineno} (in {function or '<module>'}) reads "
            f".{LOCALE_OWNER_ATTR}.{LOCALE_ATTR}, the language stored on the user row. "
            "Text a person reads is composed in the language the request asked for: "
            "depend on `RequestLocaleDep` and pass that locale instead."
        )


def test_the_only_permitted_row_reader_still_exists() -> None:
    """Keeps `LOCALE_ROW_READERS` honest.

    An exemption for a function that has been renamed or deleted is an exemption nobody
    can see is dead, and it would go on excusing whatever later took the name.
    """
    for relative, function in LOCALE_ROW_READERS:
        tree = ast.parse((APP_ROOT.parent / relative).read_text(encoding="utf-8"))
        reads = _stored_locale_reads(tree)
        assert any(name == function for name, _ in reads), (
            f"{relative} no longer reads the stored preference in {function}(); "
            "drop the entry from LOCALE_ROW_READERS"
        )


def test_the_locale_check_catches_the_shapes_it_claims_to() -> None:
    """The detector, exercised on synthetic sources — the sibling of
    `test_the_checks_actually_catch_the_escapes_they_claim_to`.

    Without this, a detector that silently matched nothing would pass every module.
    """
    caught = ast.parse("locale = authenticated.context.preferred_language")
    assert _stored_locale_reads(caught) == [(None, 1)]

    keyword = ast.parse("use_case.execute(locale=request.context.preferred_language)")
    assert _stored_locale_reads(keyword) == [(None, 1)]

    inside = ast.parse(
        "async def get_request_locale(a):\n    return f(a.context.preferred_language)"
    )
    assert _stored_locale_reads(inside) == [("get_request_locale", 2)]

    nested = ast.parse(
        "def outer():\n    def inner(a):\n        return a.context.preferred_language\n"
    )
    assert _stored_locale_reads(nested) == [("inner", 3)], "the innermost def is the name"

    # The four legitimate serialisers: the column read straight off an ORM row is a
    # one-attribute chain and must NOT match, which is what removes the need for a
    # whitelist covering them.
    row = ast.parse("Schema(preferred_language=user.preferred_language)")
    assert _stored_locale_reads(row) == []

    guest = ast.parse("Schema(preferred_language=guest.preferred_language)")
    assert _stored_locale_reads(guest) == []

    # A different attribute under `.context` is not this rule's business.
    other = ast.parse("x = authenticated.context.role")
    assert _stored_locale_reads(other) == []

    # ...and neither is `.context` reached through something that is not an attribute —
    # unless that name was itself bound to `<x>.context` first, which is the alias shape
    # below.
    literal = ast.parse("x = ctx.preferred_language")
    assert _stored_locale_reads(literal) == []

    aliased = ast.parse(
        "def get_locale(authenticated):\n"
        "    ctx = authenticated.context\n"
        "    return ctx.preferred_language\n"
    )
    assert _stored_locale_reads(aliased) == [("get_locale", 3)], (
        "binding `.context` to a local name first must not exit the ban"
    )
