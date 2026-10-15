"""The core boundary. ``poarta_contabila.core`` re-exports the deterministic core, the
code both runtimes share (the module review's direction, 2026-10-14): the same objects, no
copies, nothing from the runtime stack, no stores."""

from __future__ import annotations

import importlib
import inspect
import re
import subprocess
import sys
import types

import poarta_contabila
from poarta_contabila import core

# What the core must never pull in: the graphs, the HTTP service, the database drivers and the
# model clients belong to this runtime, not to the code another runtime pins.
RUNTIME_STACK = (
    "langgraph",
    "langchain_core",
    "fastapi",
    "starlette",
    "uvicorn",
    "psycopg",
    "psycopg_pool",
    "httpx",
    "openai",
    "google",
)


def _home(name: str, obj: object) -> str | None:
    """The declared core module that holds *obj* under *name* (the very object), if any."""
    if isinstance(obj, types.ModuleType):
        return obj.__name__ if obj.__name__ in core.CORE_MODULES_FLAT else None
    for m in core.CORE_MODULES_FLAT:
        if getattr(importlib.import_module(m), name, None) is obj:
            return m
    return None


def test_every_export_is_a_declared_module_object_not_a_copy() -> None:
    for name in core.__all__:
        assert _home(name, getattr(core, name)) is not None, name


def test_every_declared_module_exists_and_gives_the_core_a_name() -> None:
    assert all(group.startswith("core.") for group in core.CORE_MODULES)
    homes = {_home(name, getattr(core, name)) for name in core.__all__}
    for m in core.CORE_MODULES_FLAT:
        importlib.import_module(m)
        assert m in homes, f"{m} is declared but exports nothing"


def test_core_holds_no_store_and_no_graph() -> None:
    for name in core.__all__:
        obj = getattr(core, name)
        assert not name.endswith("Store"), name
        if inspect.isclass(obj):
            assert not any(c.__name__.endswith("Store") for c in obj.__mro__), name


def test_importing_the_core_pulls_no_runtime_stack() -> None:
    code = (
        "import sys, poarta_contabila.core\n"
        f"heavy = sorted({{k.split('.')[0] for k in sys.modules}} & set({RUNTIME_STACK!r}))\n"
        "print(','.join(heavy))\n"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "", out.stdout


def test_core_version_is_semver_and_names_its_tag() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+", core.CORE_VERSION)
    assert core.CORE_TAG == f"core-v{core.CORE_VERSION}"
    assert poarta_contabila.core is core


def test_the_core_answers_as_the_runtime_does() -> None:
    # no behaviour change: the core's CUI check is the runtime's own
    from poarta_contabila.types import cui_is_valid

    assert core.cui_is_valid is cui_is_valid
    assert core.cui_is_valid("1000009") and not core.cui_is_valid("1000008")
