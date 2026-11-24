"""Deterministic configuration rules engine.

Rule types supported (all data-driven from ``catalog.json``):

* availability   - an option is only offered on some models (``available_on``)
* requires       - selecting A adds B automatically (transitively)
* includes       - a package bundles options at no extra cost and locks them
* excludes       - A and B cannot be combined
* groups         - exactly one option per group (wheels, seats, paint); optional
                   groups (audio) allow at most one
* effects        - options change derived specs (range, seats, boot volume)

Changes that would silently undo something the customer chose are never applied
implicitly; they return a ``Conflict`` with explicit resolutions instead.
"""

from __future__ import annotations

from collections.abc import Iterable

from .repository import CatalogRepository
from .schemas import (
    Budget,
    ChangeRequest,
    ChangeResult,
    Conflict,
    ConfigurationView,
    Issue,
    Note,
    OptionAvailability,
    OptionLine,
    Requirements,
    Resolution,
    Saving,
    VehicleModel,
    Violation,
)


class UnknownModelError(LookupError):
    pass


def _fmt_eur(value: int) -> str:
    return f"€{value:,.0f}"


class ConfigurationEngine:
    def __init__(self, repo: CatalogRepository):
        self.repo = repo

    # ------------------------------------------------------------------ helpers

    def model(self, model_id: str) -> VehicleModel:
        model = self.repo.models.get(model_id)
        if model is None:
            raise UnknownModelError(model_id)
        return model

    def is_available(self, option_id: str, model: VehicleModel) -> bool:
        opt = self.repo.options[option_id]
        return opt.available_on == "all" or model.id in opt.available_on

    def models_offering(self, option_id: str) -> list[str]:
        return [m.name for m in self.repo.models.values() if self.is_available(option_id, m)]

    def closure(self, option_id: str) -> list[str]:
        """The option plus everything it requires or includes, transitively (stable order)."""
        result: list[str] = []
        stack = [option_id]
        while stack:
            current = stack.pop(0)
            if current in result:
                continue
            result.append(current)
            opt = self.repo.options[current]
            stack.extend(opt.requires)
            stack.extend(opt.includes)
        return result

    def included_by(self, selected: Iterable[str]) -> dict[str, str]:
        """Map option id -> package id for options locked by a selected package."""
        locked: dict[str, str] = {}
        for oid in selected:
            for inc in self.repo.options[oid].includes:
                locked[inc] = oid
        return locked

    def required_by(self, selected: Iterable[str]) -> dict[str, list[str]]:
        sel = list(selected)
        out: dict[str, list[str]] = {}
        for oid in sel:
            for req in self.repo.options[oid].requires:
                out.setdefault(req, []).append(oid)
        return out

    def dependents(self, option_id: str, selected: Iterable[str]) -> list[str]:
        """Selected options that (transitively) depend on ``option_id``."""
        sel = set(selected)
        found: list[str] = []
        frontier = [option_id]
        while frontier:
            target = frontier.pop()
            for oid in sel:
                if oid in found:
                    continue
                opt = self.repo.options[oid]
                if target in opt.requires:
                    found.append(oid)
                    frontier.append(oid)
        return found

    def standard_for_group(self, model: VehicleModel, group: str) -> str | None:
        for oid in model.standard_options:
            if self.repo.options[oid].group == group:
                return oid
        return None

    def normalize(self, model: VehicleModel, selected: Iterable[str]) -> list[str]:
        """Return a de-duplicated selection with required groups filled with standard options."""
        result: list[str] = []
        for oid in selected:
            if oid not in result:
                result.append(oid)
        for group in self.repo.groups.values():
            if not group.required:
                continue
            if not any(self.repo.options[o].group == group.id for o in result):
                std = self.standard_for_group(model, group.id)
                if std:
                    result.append(std)
        return self._ordered(result)

    def _ordered(self, options: Iterable[str]) -> list[str]:
        order = {oid: i for i, oid in enumerate(self.repo.options)}
        return sorted(set(options), key=lambda o: order.get(o, 10_000))

    def _name(self, option_id: str) -> str:
        return self.repo.options[option_id].name

    # ------------------------------------------------------------------ validation

    def validate(self, model_id: str, options: Iterable[str]) -> list[Issue]:
        model = self.model(model_id)
        sel = list(dict.fromkeys(options))
        issues: list[Issue] = []
        known = [o for o in sel if o in self.repo.options]
        for oid in sel:
            if oid not in self.repo.options:
                issues.append(Issue(code="unknown_option", message=f"Unknown option '{oid}'.", option_ids=[oid]))
        for oid in known:
            opt = self.repo.options[oid]
            if not self.is_available(oid, model):
                issues.append(
                    Issue(
                        code="not_available",
                        message=f"{opt.name} is not available on the {model.name}.",
                        option_ids=[oid],
                        alternatives=self.models_offering(oid),
                    )
                )
            for req in opt.requires + opt.includes:
                if req not in known:
                    issues.append(
                        Issue(
                            code="dependency_missing",
                            message=f"{opt.name} requires {self._name(req)}.",
                            option_ids=[oid, req],
                        )
                    )
            for exc in opt.excludes:
                if exc in known and oid < exc:
                    issues.append(
                        Issue(
                            code="excluded_combination",
                            message=f"{opt.name} cannot be combined with {self._name(exc)}.",
                            option_ids=[oid, exc],
                        )
                    )
        for group in self.repo.groups.values():
            members = [o for o in known if self.repo.options[o].group == group.id]
            if len(members) > 1:
                issues.append(
                    Issue(
                        code="group_conflict",
                        message=f"Only one {group.name.lower()} choice is allowed: "
                        + ", ".join(self._name(m) for m in members)
                        + ".",
                        option_ids=members,
                    )
                )
            if group.required and not members:
                issues.append(
                    Issue(code="group_missing", message=f"A {group.name.lower()} choice is required.", option_ids=[])
                )
        return issues

    # ------------------------------------------------------------------ pricing & view

    def specs(self, model: VehicleModel, options: Iterable[str]) -> dict:
        sel = list(options)
        range_pct = sum(self.repo.options[o].effects.range_pct for o in sel if o in self.repo.options)
        seats = model.seats + sum(self.repo.options[o].effects.seats for o in sel if o in self.repo.options)
        trunk = model.trunk_l + sum(self.repo.options[o].effects.trunk_l for o in sel if o in self.repo.options)
        electric = (
            round(model.electric_range_km * (1 + range_pct / 100)) if model.electric_range_km is not None else None
        )
        total = round(model.total_range_km * (1 + range_pct / 100)) if model.powertrain == "bev" else model.total_range_km
        return {
            "powertrain": model.powertrain,
            "body": model.body,
            "seats": seats,
            "trunk_l": trunk,
            "electric_range_km": electric,
            "total_range_km": total,
            "dc_charge_kw": model.dc_charge_kw,
            "tow_kg": model.tow_kg if "tow_hitch" in sel else 0,
            "max_tow_kg": model.tow_kg,
            "acceleration_s": model.acceleration_s,
            "rear_three_child_seats": model.rear_three_child_seats,
        }

    def price_lines(self, model: VehicleModel, options: list[str]) -> list[OptionLine]:
        locked = self.included_by(options)
        required = self.required_by(options)
        lines: list[OptionLine] = []
        for oid in options:
            opt = self.repo.options[oid]
            if oid in model.standard_options:
                lines.append(
                    OptionLine(id=oid, name=opt.name, category=opt.category, price=0, list_price=opt.price,
                               status="standard", reason="Standard equipment")
                )
            elif oid in locked:
                lines.append(
                    OptionLine(id=oid, name=opt.name, category=opt.category, price=0, list_price=opt.price,
                               status="included", reason=f"Included in {self._name(locked[oid])}")
                )
            elif oid in required:
                lines.append(
                    OptionLine(id=oid, name=opt.name, category=opt.category, price=opt.price, list_price=opt.price,
                               status="auto_added",
                               reason="Required by " + ", ".join(self._name(r) for r in required[oid]))
                )
            else:
                lines.append(
                    OptionLine(id=oid, name=opt.name, category=opt.category, price=opt.price, list_price=opt.price,
                               status="selected")
                )
        return lines

    def view(self, model_id: str, options: Iterable[str], requirements: Requirements | None = None) -> ConfigurationView:
        from .recommender import option_recommendations, requirement_violations, selection_reason  # avoid import cycle

        requirements = requirements or Requirements()
        model = self.model(model_id)
        raw = [o for o in dict.fromkeys(options)]
        known = [o for o in raw if o in self.repo.options]
        normalized = self.normalize(model, known)
        unknown = [o for o in raw if o not in self.repo.options]
        issues = self.validate(model_id, unknown + normalized)
        lines = self.price_lines(model, normalized)
        for line in lines:
            if line.status == "selected" and not line.reason:
                line.reason = selection_reason(self, model, line.id, requirements)
        options_price = sum(line.price for line in lines)
        total = model.base_price + options_price
        budget_max = requirements.budget_max
        over_by = max(0, total - budget_max) if budget_max is not None else 0
        recs = option_recommendations(self, model, normalized, requirements)
        locked = self.included_by(normalized)

        catalog_options: list[OptionAvailability] = []
        for oid, opt in self.repo.options.items():
            if oid in model.standard_options and oid in normalized:
                state, note = "standard", "Standard equipment"
            elif oid in locked:
                state, note = "included", f"Included in {self._name(locked[oid])}"
            elif oid in normalized:
                state, note = "selected", ""
            elif not self.is_available(oid, model):
                state, note = "unavailable", f"Not offered on the {model.series}"
            else:
                state, note = "available", ""
            catalog_options.append(
                OptionAvailability(
                    id=oid, name=opt.name, category=opt.category, group=opt.group,
                    price=0 if oid in model.standard_options else opt.price,
                    description=opt.description, state=state, note=note,
                    recommended=oid in recs, recommended_reason=recs.get(oid, ""),
                )
            )

        return ConfigurationView(
            model_id=model.id,
            model_name=model.name,
            options=normalized,
            lines=lines,
            base_price=model.base_price,
            options_price=options_price,
            total_price=total,
            specs=self.specs(model, normalized),
            valid=not issues,
            issues=issues,
            budget=Budget(
                max=budget_max,
                total=total,
                remaining=(budget_max - total) if budget_max is not None else None,
                over_by=over_by,
            ),
            savings=self._savings(model, normalized, over_by, requirements) if over_by else [],
            catalog_options=catalog_options,
            unmet_requirements=requirement_violations(self, model, normalized, requirements),
        )

    def _savings(self, model: VehicleModel, options: list[str], over_by: int, req: Requirements) -> list[Saving]:
        """Removable options (not standard, not needed for requirements), biggest saving first."""
        from .recommender import options_needed_for

        needed = options_needed_for(self, model, req)
        protected = set(model.standard_options) | {o for n in needed for o in self.closure(n)}
        locked = self.included_by(options)
        savings: list[Saving] = []
        for oid in options:
            if oid in protected or oid in locked:
                continue
            removed = {oid, *self.dependents(oid, options)}
            saves = sum(line.price for line in self.price_lines(model, options) if line.id in removed)
            if saves > 0:
                name = self._name(oid)
                others = [self._name(d) for d in removed if d != oid]
                if others:
                    name += " (and " + ", ".join(others) + ", which need it)"
                savings.append(Saving(option_id=oid, name=name, saves=saves))
        savings.sort(key=lambda s: -s.saves)
        return savings[:5]

    # ------------------------------------------------------------------ changes

    def apply(self, model_id: str, options: Iterable[str], change: ChangeRequest,
              requirements: Requirements | None = None) -> ChangeResult:
        model = self.model(model_id)
        current = self.normalize(model, [o for o in options if o in self.repo.options])
        if change.action == "add":
            status, new, notes, conflict, error = self._add(model, current, change)
        else:
            status, new, notes, conflict, error = self._remove(model, current, change)
        return ChangeResult(
            status=status,
            notes=notes,
            conflict=conflict,
            error=error,
            configuration=self.view(model_id, new, requirements),
        )

    def _add(self, model: VehicleModel, current: list[str], change: ChangeRequest):
        oid = change.option_id
        if oid not in self.repo.options:
            return "rejected", current, [], None, Issue(
                code="unknown_option", message=f"There is no option called '{oid}' in the catalog.", option_ids=[oid]
            )
        opt = self.repo.options[oid]
        if not self.is_available(oid, model):
            alternatives = self.models_offering(oid)
            hint = f" It is available on: {', '.join(alternatives)}." if alternatives else ""
            return "rejected", current, [], None, Issue(
                code="not_available",
                message=f"{opt.name} is not available on the {model.name}.{hint}",
                option_ids=[oid],
                alternatives=alternatives,
            )
        locked = self.included_by(current)
        if oid in current or oid in locked:
            where = f" (included in {self._name(locked[oid])})" if oid in locked else ""
            return "noop", current, [Note(kind="info", option_id=oid, message=f"{opt.name} is already part of the configuration{where}.")], None, None

        to_add = self.closure(oid)
        for dep in to_add[1:]:
            if not self.is_available(dep, model):
                return "rejected", current, [], None, Issue(
                    code="dependency_unavailable",
                    message=f"{opt.name} needs {self._name(dep)}, which is not offered on the {model.name}.",
                    option_ids=[oid, dep],
                )

        # Work out what the addition displaces, and why.
        displaced: dict[str, str] = {}  # option -> reason
        silent: set[str] = set()
        for added in to_add:
            a = self.repo.options[added]
            for sel in current:
                if sel in to_add or sel in displaced:
                    continue
                s = self.repo.options[sel]
                if a.group and s.group == a.group:
                    displaced[sel] = f"{a.name} would replace {s.name}"
                    # replacing within the group the customer clicked, or replacing a standard item, is expected
                    if (added == oid and sel not in locked) or sel in model.standard_options:
                        silent.add(sel)
                elif sel in a.excludes or added in s.excludes:
                    displaced[sel] = f"{a.name} cannot be combined with {s.name}"
        # Displacing an item locked in a package removes the package (and its other contents).
        changed = True
        while changed:
            changed = False
            for sel in list(displaced):
                pkg = locked.get(sel)
                if pkg and pkg not in displaced and pkg not in to_add:
                    displaced[pkg] = f"{self._name(sel)} is part of the {self._name(pkg)}"
                    changed = True
            for sel in list(displaced):
                if self.repo.options[sel].includes:
                    for inc in self.repo.options[sel].includes:
                        if inc in current and inc not in displaced and inc not in to_add:
                            displaced[inc] = f"comes with {self._name(sel)}"
                            silent.add(inc)
                            changed = True
                for dep in self.dependents(sel, current):
                    if dep not in displaced and dep not in to_add:
                        displaced[dep] = f"{self._name(dep)} requires {self._name(sel)}"
                        changed = True

        significant = [d for d in displaced if d not in silent]
        if significant and not change.force:
            # Only name the top-level items; things locked in a removed package go with it.
            shown = [d for d in significant if locked.get(d) not in displaced]
            removed_names = ", ".join(self._name(d) for d in shown)
            reasons = "; ".join(displaced[d] for d in significant)
            return "conflict", current, [], Conflict(
                message=f"{opt.name} conflicts with your configuration: {reasons}. Adding it removes {removed_names}.",
                option_ids=[oid, *significant],
                resolutions=[
                    Resolution(label=f"Add {opt.name}, remove {removed_names}",
                               change=ChangeRequest(action="add", option_id=oid, force=True)),
                    Resolution(label=f"Keep {removed_names}", change=None),
                ],
            ), None

        new = [o for o in current if o not in displaced] + to_add
        new = self.normalize(model, new)
        notes: list[Note] = [Note(kind="info", option_id=oid, message=f"Added {opt.name}.")]
        for pkg in to_add:
            included = [i for i in self.repo.options[pkg].includes if i not in current]
            if included:
                notes.append(Note(kind="info", option_id=pkg, message=f"{self._name(pkg)} includes "
                                  + ", ".join(self._name(i) for i in included) + " at no extra cost."))
        for dep in to_add[1:]:
            requirer = next((x for x in to_add if dep in self.repo.options[x].requires), None)
            if dep not in current and requirer:
                notes.append(Note(kind="auto_added", option_id=dep,
                                  message=f"Also added {self._name(dep)} because {self._name(requirer)} requires it."))
        for d, reason in displaced.items():
            if d in silent and d in model.standard_options:
                continue  # replacing standard equipment needs no explanation
            kind = "replaced" if d in silent else "removed"
            notes.append(Note(kind=kind, option_id=d, message=f"Removed {self._name(d)}: {reason}."))
        return "applied", new, notes, None, None

    def _remove(self, model: VehicleModel, current: list[str], change: ChangeRequest):
        oid = change.option_id
        if oid not in self.repo.options:
            return "rejected", current, [], None, Issue(
                code="unknown_option", message=f"There is no option called '{oid}'.", option_ids=[oid]
            )
        opt = self.repo.options[oid]
        locked = self.included_by(current)
        if oid in locked:
            pkg = locked[oid]
            if not change.force:
                return "conflict", current, [], Conflict(
                    message=f"{opt.name} is part of the {self._name(pkg)}. Removing it means removing the package.",
                    option_ids=[oid, pkg],
                    resolutions=[
                        Resolution(label=f"Remove {self._name(pkg)}",
                                   change=ChangeRequest(action="remove", option_id=pkg, force=True)),
                        Resolution(label="Keep the package", change=None),
                    ],
                ), None
            return self._remove(model, current, ChangeRequest(action="remove", option_id=pkg, force=True))
        if oid not in current:
            return "noop", current, [Note(kind="info", option_id=oid, message=f"{opt.name} is not in the configuration.")], None, None
        group = self.repo.groups.get(opt.group) if opt.group else None
        if group and group.required and oid in model.standard_options:
            return "rejected", current, [], None, Issue(
                code="not_removable",
                message=f"{opt.name} is the standard {group.name.lower()} choice; pick another {group.name.lower()} option instead.",
                option_ids=[oid],
            )
        dependents = self.dependents(oid, current)
        if dependents and not change.force:
            names = ", ".join(self._name(d) for d in dependents)
            return "conflict", current, [], Conflict(
                message=f"{names} requires {opt.name}.",
                option_ids=[oid, *dependents],
                resolutions=[
                    Resolution(label=f"Remove {opt.name} and {names}",
                               change=ChangeRequest(action="remove", option_id=oid, force=True)),
                    Resolution(label=f"Keep {opt.name}", change=None),
                ],
            ), None
        removed = {oid, *dependents}
        contents: list[str] = []
        for r in list(removed):
            for inc in self.repo.options[r].includes:
                removed.add(inc)
                contents.append(inc)
        new = self.normalize(model, [o for o in current if o not in removed])
        message = f"Removed {opt.name}"
        if dependents:
            message += " and " + ", ".join(self._name(d) for d in dependents) + " (which require it)"
        if contents:
            message += " including " + ", ".join(self._name(c) for c in contents)
        notes = [Note(kind="removed", option_id=oid, message=message + ".")]
        restored = [o for o in new if o not in current]
        notes += [Note(kind="info", option_id=r, message=f"{self._name(r)} restored as standard.") for r in restored]
        return "applied", new, notes, None, None

    def switch_model(self, new_model_id: str, previous: Iterable[str], requirements: Requirements | None = None) -> ChangeResult:
        """Carry compatible customer choices over to another model, reporting what was dropped."""
        model = self.model(new_model_id)
        options = self.normalize(model, [])
        notes: list[Note] = []
        prev = [o for o in dict.fromkeys(previous) if o in self.repo.options]
        # Packages first so that their contents are not re-added individually.
        prev.sort(key=lambda o: 0 if self.repo.options[o].includes else 1)
        carried_locked: set[str] = set()
        for oid in prev:
            if oid in options or oid in carried_locked:
                continue
            opt = self.repo.options[oid]
            if oid in self.repo.models[new_model_id].standard_options:
                continue
            if opt.group and self.repo.options[oid].price == 0:
                continue
            status, new, _notes, conflict, error = self._add(model, options, ChangeRequest(action="add", option_id=oid))
            if status == "applied":
                options = new
                carried_locked |= set(opt.includes)
            elif status == "noop":
                continue
            else:
                reason = error.message if error else (conflict.message if conflict else "")
                notes.append(Note(kind="dropped", option_id=oid, message=f"Dropped {opt.name}: {reason}"))
        return ChangeResult(status="applied", notes=notes, configuration=self.view(new_model_id, options, requirements))

    # used by recommender
    def entry_configuration(self, model: VehicleModel, needed: list[str]) -> tuple[list[str], list[Issue]]:
        options = self.normalize(model, [])
        problems: list[Issue] = []
        for oid in needed:
            status, new, _n, conflict, error = self._add(model, options, ChangeRequest(action="add", option_id=oid, force=True))
            if status in ("applied", "noop"):
                options = new
            elif error:
                problems.append(error)
        return options, problems

    def price_of(self, model: VehicleModel, options: list[str]) -> int:
        return model.base_price + sum(line.price for line in self.price_lines(model, options))


__all__ = ["ConfigurationEngine", "UnknownModelError", "Violation", "_fmt_eur"]
