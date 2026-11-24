"""Loads the catalog and checks its referential integrity at start-up.

In production this would be a read-through cache in front of the product
information / pricing systems; the interface (``models``, ``options``,
``groups``) stays the same.
"""

from __future__ import annotations

import json
from pathlib import Path

from .schemas import Catalog, Group, Option, VehicleModel

DEFAULT_PATH = Path(__file__).parent / "data" / "catalog.json"


class CatalogIntegrityError(ValueError):
    pass


class CatalogRepository:
    def __init__(self, catalog: Catalog):
        self.catalog = catalog
        self.models: dict[str, VehicleModel] = {m.id: m for m in catalog.models}
        self.options: dict[str, Option] = {o.id: o for o in catalog.options}
        self.groups: dict[str, Group] = {g.id: g for g in catalog.groups}
        self._check_integrity()

    @classmethod
    def from_file(cls, path: Path = DEFAULT_PATH) -> "CatalogRepository":
        with open(path, encoding="utf-8") as fh:
            return cls(Catalog.model_validate(json.load(fh)))

    def _check_integrity(self) -> None:
        errors: list[str] = []
        for opt in self.options.values():
            for ref in opt.requires + opt.excludes + opt.includes:
                if ref not in self.options:
                    errors.append(f"option {opt.id} references unknown option {ref}")
            if opt.group and opt.group not in self.groups:
                errors.append(f"option {opt.id} has unknown group {opt.group}")
            if opt.available_on != "all":
                for mid in opt.available_on:
                    if mid not in self.models:
                        errors.append(f"option {opt.id} available_on unknown model {mid}")
        for model in self.models.values():
            for std in model.standard_options:
                if std not in self.options:
                    errors.append(f"model {model.id} has unknown standard option {std}")
            for group in self.groups.values():
                if group.required and not any(
                    self.options[s].group == group.id for s in model.standard_options if s in self.options
                ):
                    errors.append(f"model {model.id} has no standard option for required group {group.id}")
        if errors:
            raise CatalogIntegrityError("; ".join(errors))
