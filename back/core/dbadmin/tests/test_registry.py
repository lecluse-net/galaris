from __future__ import annotations

import pytest
from sqlalchemy import Column, Integer, MetaData, Table

from core.dbadmin import DbAdminDataSource, DbAdminDataset, DbAdminRegistry
from modules import load_dbadmin_contributions


_TABLE = Table("registry_probe", MetaData(), Column("id", Integer, primary_key=True))


def _dataset(key: str, *depends_on: str) -> DbAdminDataset:
    return DbAdminDataset(
        key=key,
        table=_TABLE,
        natural_key=("id",),
        rows=(),
        depends_on=depends_on,
    )


def _source(key: str, *datasets: DbAdminDataset) -> DbAdminDataSource:
    return DbAdminDataSource(key=key, factory=lambda: datasets)


def test_module_data_sources_compile_and_topologically_order_datasets() -> None:
    registry = DbAdminRegistry()
    registry.register_data_source(
        _source(
            "module.reference",
            _dataset("last", "middle"),
            _dataset("first"),
            _dataset("middle", "first"),
        )
    )

    assert [dataset.key for dataset in registry.datasets] == [
        "first",
        "middle",
        "last",
    ]


def test_duplicate_dataset_from_two_sources_is_rejected() -> None:
    registry = DbAdminRegistry()
    registry.register_data_source(_source("one", _dataset("shared")))
    registry.register_data_source(_source("two", _dataset("shared")))

    with pytest.raises(ValueError, match="Duplicate DbAdmin dataset key 'shared'"):
        _ = registry.datasets


def test_unknown_dataset_dependency_is_rejected() -> None:
    registry = DbAdminRegistry()
    registry.register_data_source(_source("module", _dataset("dependent", "missing")))

    with pytest.raises(ValueError, match="unknown keys: missing"):
        _ = registry.datasets


def test_dataset_dependency_cycle_is_rejected() -> None:
    registry = DbAdminRegistry()
    registry.register_data_source(
        _source("module", _dataset("one", "two"), _dataset("two", "one"))
    )

    with pytest.raises(ValueError, match="dependency cycle: one, two"):
        _ = registry.datasets


def test_composition_compiles_every_permanent_dataset_and_reconciler() -> None:
    registry = DbAdminRegistry()

    load_dbadmin_contributions(registry)

    source_keys = {source.key for source in registry.data_sources}
    assert {
        "app.llm",
        "app.skill",
        "app.tools",
        "core.authorize",
        "core.params",
    } <= source_keys
    # Additional active modules may contribute their own domain datasets; this
    # contract owns the permanent DbAdmin foundation listed below.
    dataset_keys = {dataset.key for dataset in registry.datasets}
    assert {
        "app.llm.current_profile",
        "app.llm.default_profile",
        "app.skill.assignments",
        "app.skill.installed",
        "app.skill.system",
        "app.tools.mandatory.connections",
        "app.tools.mandatory.tools",
        "core.authorize.admin_grants",
        "core.authorize.admin_role",
        "core.authorize.privileges",
        "core.params.declarations",
    } <= dataset_keys
    # Module-local tests own additional contributions. Adding an independent
    # reconciler must not invalidate the existing composition contract.
    assert {
        "app.dream.topic_assignments",
        "app.harnesses.catalogue_runtime_backfill",
        "app.memory.goal_document_paths",
        "app.memory.semantic_index",
        "app.memory.source_projections",
        "app.messenger.agent_identities",
        "app.messenger.contact_memory",
        "bridge.hermes.config_reconciliation",
        "bridge.hermes.data_env_encryption",
        "bridge.hermes.session_bindings",
    } <= {reconciler.key for reconciler in registry.reconcilers}
