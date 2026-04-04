from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CollectionSpec:
    name: str
    mongo_name: str
    module_name: str


COLLECTION_SPECS: dict[str, CollectionSpec] = {
    "dou_documents": CollectionSpec(
        name="dou_documents",
        mongo_name="documents",
        module_name="ops.migrations.dou_documents",
    ),
    "tcu_acordaos": CollectionSpec(
        name="tcu_acordaos",
        mongo_name="tcu_acordaos",
        module_name="ops.migrations.tcu_acordaos",
    ),
    "tcu_normas": CollectionSpec(
        name="tcu_normas",
        mongo_name="tcu_normas",
        module_name="ops.migrations.tcu_normas",
    ),
    "tcu_btcu": CollectionSpec(
        name="tcu_btcu",
        mongo_name="tcu_btcu",
        module_name="ops.migrations.tcu_btcu",
    ),
    "tcu_publicacoes": CollectionSpec(
        name="tcu_publicacoes",
        mongo_name="tcu_publicacoes",
        module_name="ops.migrations.tcu_publicacoes",
    ),
}


def resolve_specs(collections_arg: str) -> list[CollectionSpec]:
    if collections_arg.strip().lower() == "all":
        return list(COLLECTION_SPECS.values())

    names = [name.strip() for name in collections_arg.split(",") if name.strip()]
    unknown = [name for name in names if name not in COLLECTION_SPECS]
    if unknown:
        known = ", ".join(COLLECTION_SPECS)
        raise SystemExit(f"Unknown collections: {unknown!r}. Known: {known}")
    return [COLLECTION_SPECS[name] for name in names]