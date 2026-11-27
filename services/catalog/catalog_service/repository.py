"""Loads the catalog and checks its referential integrity at start-up.

In production this would be a read-through cache in front of the product
information / pricing systems; the interface (``models``, ``options``,
``groups``) stays the same.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import i18n
from .schemas import Catalog, Group, Option, VehicleModel

DEFAULT_PATH = Path(__file__).parent / "data" / "catalog.json"


class CatalogIntegrityError(ValueError):
    pass


class _Localized:
    def __init__(self, catalog: Catalog):
        self.catalog = catalog
        self.models: dict[str, VehicleModel] = {m.id: m for m in catalog.models}
        self.options: dict[str, Option] = {o.id: o for o in catalog.options}
        self.groups: dict[str, Group] = {g.id: g for g in catalog.groups}


def translate(catalog: Catalog, overlay: dict) -> Catalog:
    """Apply a translation overlay (names, descriptions, summaries); ids, prices and rules stay the same."""
    def merged(items, section):
        return [item.model_copy(update=overlay.get(section, {}).get(item.id, {})) for item in items]
    return catalog.model_copy(update={
        "disclaimer": overlay.get("disclaimer", catalog.disclaimer),
        "groups": merged(catalog.groups, "groups"),
        "models": merged(catalog.models, "models"),
        "options": merged(catalog.options, "options"),
    })


class CatalogRepository:
    """The catalog in every supported language; ``models``, ``options`` etc. follow the request's language."""

    def __init__(self, catalog: Catalog, translations: dict[str, dict] | None = None):
        self._by_lang = {i18n.DEFAULT: _Localized(catalog)}
        for code, overlay in (translations or {}).items():
            self._by_lang[code] = _Localized(translate(catalog, overlay))
        self._check_integrity(self._by_lang[i18n.DEFAULT])
        self._check_translations(catalog, translations or {})

    @property
    def _current(self) -> _Localized:
        return self._by_lang.get(i18n.lang(), self._by_lang[i18n.DEFAULT])

    @property
    def catalog(self) -> Catalog:
        return self._current.catalog

    @property
    def models(self) -> dict[str, VehicleModel]:
        return self._current.models

    @property
    def options(self) -> dict[str, Option]:
        return self._current.options

    @property
    def groups(self) -> dict[str, Group]:
        return self._current.groups

    @classmethod
    def from_file(cls, path: Path = DEFAULT_PATH) -> "CatalogRepository":
        with open(path, encoding="utf-8") as fh:
            catalog = Catalog.model_validate(json.load(fh))
        translations = {}
        for code in i18n.LANGUAGES:
            overlay = path.parent / "i18n" / f"{code}.json"
            if code != i18n.DEFAULT and overlay.exists():
                translations[code] = json.loads(overlay.read_text(encoding="utf-8"))
        return cls(catalog, translations)

    @staticmethod
    def _check_translations(catalog: Catalog, translations: dict[str, dict]) -> None:
        """Every option and group needs a translation, so no English slips into another language."""
        errors: list[str] = []
        for code, overlay in translations.items():
            for section, items in (("options", catalog.options), ("groups", catalog.groups)):
                missing = sorted(i.id for i in items if i.id not in overlay.get(section, {}))
                if missing:
                    errors.append(f"{code}: no translation for {section} {missing}")
        if errors:
            raise CatalogIntegrityError("; ".join(errors))

    @staticmethod
    def _check_integrity(cat: _Localized) -> None:
        """Ids are the same in every language, so checking the default catalog covers all of them."""
        errors: list[str] = []
        for opt in cat.options.values():
            for ref in opt.requires + opt.excludes + opt.includes:
                if ref not in cat.options:
                    errors.append(f"option {opt.id} references unknown option {ref}")
            if opt.group and opt.group not in cat.groups:
                errors.append(f"option {opt.id} has unknown group {opt.group}")
            if opt.available_on != "all":
                for mid in opt.available_on:
                    if mid not in cat.models:
                        errors.append(f"option {opt.id} available_on unknown model {mid}")
        for model in cat.models.values():
            for std in model.standard_options:
                if std not in cat.options:
                    errors.append(f"model {model.id} has unknown standard option {std}")
            for group in cat.groups.values():
                if group.required and not any(
                    cat.options[s].group == group.id for s in model.standard_options if s in cat.options
                ):
                    errors.append(f"model {model.id} has no standard option for required group {group.id}")
        if errors:
            raise CatalogIntegrityError("; ".join(errors))
