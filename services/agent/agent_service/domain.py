"""Customer requirements as seen by the agent (contract shared with the catalog service)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Powertrain = Literal["bev", "phev", "petrol", "diesel"]
Body = Literal["gran_coupe", "touring", "sav", "tourer", "sedan"]

POWERTRAIN_LABEL = {"bev": "electric", "phev": "plug-in hybrid", "petrol": "petrol", "diesel": "diesel"}
BODY_LABEL = {"gran_coupe": "Gran Coupé", "touring": "estate (Touring)", "sav": "SUV (SAV)", "tourer": "compact tourer", "sedan": "saloon"}


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
        """(field, human label) pairs for the 'what I understood' panel."""
        out: list[tuple[str, str]] = []
        if self.budget_max is not None:
            out.append(("budget_max", f"Budget up to €{self.budget_max:,}"))
        if self.powertrain_required:
            out.append(("powertrain_required", "Must be " + " or ".join(POWERTRAIN_LABEL[p] for p in self.powertrain_required)))
        if self.powertrain_preferred:
            out.append(("powertrain_preferred", "Prefers " + " or ".join(POWERTRAIN_LABEL[p] for p in self.powertrain_preferred)))
        if self.child_seats:
            out.append(("child_seats", f"{self.child_seats} child seat{'s' if self.child_seats > 1 else ''}"))
        if self.min_seats:
            out.append(("min_seats", f"At least {self.min_seats} seats"))
        if self.long_distance:
            out.append(("long_distance", "Regular long-distance trips"))
        if self.towing_kg is not None:
            out.append(("towing_kg", "Bike carrier" if self.towing_kg == 0 else f"Towing {self.towing_kg:,} kg"))
        if self.min_trunk_l:
            out.append(("min_trunk_l", f"Boot ≥ {self.min_trunk_l} l"))
        if self.body_styles:
            out.append(("body_styles", " or ".join(BODY_LABEL[b] for b in self.body_styles)))
        if self.sportiness is not None:
            pct = round(self.sportiness * 100)
            label = "Comfort-focused" if pct < 40 else "Sporty" if pct > 60 else "Balanced comfort/sport"
            out.append(("sportiness", label))
        if self.must_have_options:
            out.append(("must_have_options", f"{len(self.must_have_options)} must-have option(s)"))
        return out
