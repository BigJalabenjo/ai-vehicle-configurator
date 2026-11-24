"""Domain and API schemas for the catalog / configuration service.

The catalog service is the single source of truth for products, prices and
configuration rules. The agent never invents these values; it only calls the
endpoints defined in ``main.py`` which return these schemas.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Powertrain = Literal["bev", "phev", "petrol", "diesel"]
Body = Literal["gran_coupe", "touring", "sav", "tourer", "sedan"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- catalog


class Effects(_Strict):
    range_pct: float = 0
    seats: int = 0
    trunk_l: int = 0


class Option(_Strict):
    id: str
    name: str
    category: str
    price: int = Field(ge=0)
    description: str = ""
    group: str | None = None
    available_on: list[str] | Literal["all"] = "all"
    requires: list[str] = []
    excludes: list[str] = []
    includes: list[str] = []  # only for packages
    effects: Effects = Effects()
    tags: list[str] = []

    @property
    def is_package(self) -> bool:
        return bool(self.includes)


class Group(_Strict):
    id: str
    name: str
    required: bool


class VehicleModel(_Strict):
    id: str
    name: str
    series: str
    body: Body
    powertrain: Powertrain
    base_price: int
    seats: int
    rear_three_child_seats: bool
    trunk_l: int
    electric_range_km: int | None
    total_range_km: int
    dc_charge_kw: int | None
    tow_kg: int
    acceleration_s: float
    sport: float = Field(ge=0, le=1)
    comfort: float = Field(ge=0, le=1)
    standard_options: list[str]
    summary: str


class Catalog(_Strict):
    version: str
    currency: str
    disclaimer: str
    groups: list[Group]
    models: list[VehicleModel]
    options: list[Option]


# --------------------------------------------------------------------------- requirements


class Requirements(BaseModel):
    """Structured customer needs. Every field is optional; unknown means 'no constraint'."""

    budget_max: int | None = Field(default=None, ge=0, description="Maximum total price in EUR")
    powertrain_preferred: list[Powertrain] = Field(default=[], description="Soft preference")
    powertrain_required: list[Powertrain] = Field(default=[], description="Hard constraint")
    min_seats: int | None = Field(default=None, ge=2, le=9)
    child_seats: int | None = Field(default=None, ge=0, le=6, description="Number of child seats needed")
    long_distance: bool = False
    towing_kg: int | None = Field(default=None, ge=0, description="Trailer weight; 0 = bike carrier only")
    min_trunk_l: int | None = Field(default=None, ge=0)
    body_styles: list[Body] = []
    sportiness: float | None = Field(default=None, ge=0, le=1, description="0 = comfort, 1 = sporty")
    must_have_options: list[str] = []


# --------------------------------------------------------------------------- recommendation


class Violation(BaseModel):
    code: Literal[
        "budget", "powertrain", "seats", "child_seats", "towing", "range", "trunk", "body", "option_unavailable"
    ]
    message: str
    relax_patch: dict = Field(default_factory=dict, description="Requirements patch that removes this violation")
    relax_label: str = ""


class ModelEvaluation(BaseModel):
    model_id: str
    name: str
    body: str
    powertrain: str
    base_price: int
    entry_price: int = Field(description="Base price plus options needed to meet the requirements")
    required_options: list[str]
    fits: bool
    score: float
    reasons: list[str]
    violations: list[Violation]
    specs: dict


class Tradeoff(BaseModel):
    label: str
    description: str
    model_id: str
    relax_patch: dict


class RecommendRequest(BaseModel):
    requirements: Requirements = Requirements()
    model_ids: list[str] | None = None
    limit: int = Field(default=3, ge=1, le=10)


class RecommendResponse(BaseModel):
    fits: list[ModelEvaluation]
    near_misses: list[ModelEvaluation]
    tradeoffs: list[Tradeoff]
    explanation: str


# --------------------------------------------------------------------------- configuration


class Note(BaseModel):
    kind: Literal["auto_added", "replaced", "removed", "dropped", "info"]
    option_id: str
    message: str


class Issue(BaseModel):
    code: Literal[
        "unknown_model",
        "unknown_option",
        "not_available",
        "dependency_missing",
        "dependency_unavailable",
        "excluded_combination",
        "group_conflict",
        "group_missing",
        "not_removable",
        "part_of_package",
    ]
    message: str
    option_ids: list[str] = []
    alternatives: list[str] = Field(default=[], description="Human readable alternatives, e.g. models offering it")


class ChangeRequest(BaseModel):
    action: Literal["add", "remove"]
    option_id: str
    force: bool = False


class Resolution(BaseModel):
    label: str
    change: ChangeRequest | None = Field(description="None = keep the current configuration")


class Conflict(BaseModel):
    message: str
    option_ids: list[str]
    resolutions: list[Resolution]


class OptionLine(BaseModel):
    id: str
    name: str
    category: str
    price: int = Field(description="Price charged in this configuration")
    list_price: int
    status: Literal["standard", "selected", "included", "auto_added"]
    reason: str = ""


class OptionAvailability(BaseModel):
    id: str
    name: str
    category: str
    group: str | None
    price: int
    description: str
    state: Literal["standard", "selected", "included", "available", "unavailable"]
    note: str = ""
    recommended: bool = False
    recommended_reason: str = ""


class Budget(BaseModel):
    max: int | None
    total: int
    remaining: int | None
    over_by: int


class Saving(BaseModel):
    option_id: str
    name: str
    saves: int


class ConfigurationView(BaseModel):
    model_id: str
    model_name: str
    options: list[str]
    lines: list[OptionLine]
    base_price: int
    options_price: int
    total_price: int
    specs: dict
    valid: bool
    issues: list[Issue]
    budget: Budget
    savings: list[Saving]
    catalog_options: list[OptionAvailability]
    unmet_requirements: list[Violation]


class ConfigurationRequest(BaseModel):
    model_id: str
    options: list[str] = []
    requirements: Requirements = Requirements()


class ChangeConfigurationRequest(ConfigurationRequest):
    change: ChangeRequest


class SwitchModelRequest(BaseModel):
    new_model_id: str
    previous_options: list[str] = []
    requirements: Requirements = Requirements()


class ChangeResult(BaseModel):
    status: Literal["applied", "conflict", "rejected", "noop"]
    notes: list[Note] = []
    conflict: Conflict | None = None
    error: Issue | None = None
    configuration: ConfigurationView
