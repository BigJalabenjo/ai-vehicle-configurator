"""Customer requirements as seen by the agent (contract shared with the catalog service)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .i18n import eur, join_or, num, t, words

Powertrain = Literal["bev", "phev", "petrol", "diesel"]
Body = Literal["gran_coupe", "touring", "sav", "tourer", "sedan"]


class Requirements(BaseModel):
    model_config = ConfigDict(extra="forbid")

    budget_max: int | None = Field(default=None, ge=0, le=1_000_000)
    powertrain_preferred: list[Powertrain] = []
    powertrain_required: list[Powertrain] = []
    min_seats: int | None = Field(default=None, ge=2, le=9)
    child_seats: int | None = Field(default=None, ge=0, le=6)
    long_distance: bool = False
    towing_kg: int | None = Field(default=None, ge=0, le=5000)
    min_trunk_l: int | None = Field(default=None, ge=0, le=2000)
    body_styles: list[Body] = []
    sportiness: float | None = Field(default=None, ge=0, le=1)
    must_have_options: list[str] = []

    def merged(self, patch: dict) -> "Requirements":
        """Return a new, validated Requirements with ``patch`` applied (None clears a field)."""
        data = self.model_dump()
        for key, value in patch.items():
            if key not in data:
                raise ValueError(f"Unknown requirement '{key}'")
            if value is None:
                data[key] = Requirements.model_fields[key].get_default(call_default_factory=True)
            else:
                data[key] = value
        return Requirements.model_validate(data)

    def describe(self) -> list[tuple[str, str]]:
        """(field, human label) pairs for the 'what I understood' panel, in the session's language."""
        out: list[tuple[str, str]] = []
        pt = words("powertrain")
        if self.budget_max is not None:
            out.append(("budget_max", t("need_budget", amount=eur(self.budget_max))))
        if self.powertrain_required:
            out.append(("powertrain_required", t("need_must_be", pts=join_or([pt[p] for p in self.powertrain_required]))))
        if self.powertrain_preferred:
            out.append(("powertrain_preferred", t("need_prefers", pts=join_or([pt[p] for p in self.powertrain_preferred]))))
        if self.child_seats:
            out.append(("child_seats", t("need_child_seats" if self.child_seats > 1 else "need_child_seat", n=self.child_seats)))
        if self.min_seats:
            out.append(("min_seats", t("need_min_seats", n=self.min_seats)))
        if self.long_distance:
            out.append(("long_distance", t("need_long_distance")))
        if self.towing_kg is not None:
            out.append(("towing_kg", t("need_bike_carrier") if self.towing_kg == 0 else t("need_towing", kg=num(self.towing_kg))))
        if self.min_trunk_l:
            out.append(("min_trunk_l", t("need_trunk", l=self.min_trunk_l)))
        if self.body_styles:
            out.append(("body_styles", join_or([words("body")[b] for b in self.body_styles])))
        if self.sportiness is not None:
            pct = round(self.sportiness * 100)
            out.append(("sportiness", t("need_comfort") if pct < 40 else t("need_sporty") if pct > 60 else t("need_balanced")))
        if self.must_have_options:
            names = [o.removeprefix("pkg_").replace("_", " ") for o in self.must_have_options]
            out.append(("must_have_options", t("need_must_have", names=", ".join(names))))
        return out
