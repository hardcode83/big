"""Importing the app must register every domain's models (R4.2, design D16).

The global tenant filter is built from `Base.registry.mappers`, so a model module the
running application never imports is a table the net never protects. (The scan used to
be memoised on first use, which made it worse; that was removed — see the docstring of
`tenant_scoped_classes` in app/core/db.py.) The test process imports everything through conftest, which is
exactly why this needs checking in a subprocess that imports only `app.main`.
"""

import subprocess
import sys
from pathlib import Path

from app.core.models_registry import DOMAIN_MODEL_MODULES

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_the_registry_lists_every_domain_that_has_models() -> None:
    on_disk = {
        f"app.{path.parts[-3]}.infrastructure.models"
        for path in BACKEND_ROOT.glob("app/*/infrastructure/models.py")
    }

    assert on_disk == set(DOMAIN_MODEL_MODULES), (
        "app/core/models_registry.py is out of step with the domains on disk; "
        "a missing entry means the tenant filter does not cover that domain's tables"
    )


def test_importing_app_main_registers_every_domain_model() -> None:
    # A subprocess, because this test session already imported everything.
    probe = (
        "import app.main, sys;"
        "from app.core.models_registry import DOMAIN_MODEL_MODULES;"
        "missing = [m for m in DOMAIN_MODEL_MODULES if m not in sys.modules];"
        "print(','.join(missing))"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "", f"not registered by app.main: {result.stdout.strip()}"


def test_the_tenant_filter_sees_the_child_tables_that_have_no_tenant_id_of_their_own() -> None:
    """Pins design D16's fifth limit rather than leaving it implicit.

    `messages`, `cleaning_checklist_completions` and `cleaning_photos` carry no
    `tenant_id` — they hang off a tenant-scoped parent. The net matches on column
    presence, so it does NOT cover them: any repository touching them must join the
    scoped parent explicitly and carry its own isolation test.
    """
    from app.core.db import tenant_scoped_classes

    covered = {entity.__tablename__ for entity in tenant_scoped_classes()}

    assert "messages" not in covered
    assert "cleaning_checklist_completions" not in covered
    assert "cleaning_photos" not in covered
