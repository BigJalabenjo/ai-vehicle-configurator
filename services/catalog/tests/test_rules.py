import pytest

from catalog_service.repository import CatalogIntegrityError, CatalogRepository
from catalog_service.rules import ConfigurationEngine, UnknownModelError
from catalog_service.schemas import ChangeRequest, Requirements

I5 = "i5_touring_edrive40"


@pytest.fixture(scope="module")
def engine() -> ConfigurationEngine:
    return ConfigurationEngine(CatalogRepository.from_file())


def add(engine, options, oid, force=False, model=I5, req=None):
    return engine.apply(model, options, ChangeRequest(action="add", option_id=oid, force=force), req)


def remove(engine, options, oid, force=False, model=I5):
    return engine.apply(model, options, ChangeRequest(action="remove", option_id=oid, force=force))


def base(engine, model=I5):
    return engine.view(model, []).options


def test_catalog_integrity_is_checked():
    repo = CatalogRepository.from_file()
    bad = repo.catalog.model_copy(deep=True)
    bad.options[0].requires = ["does_not_exist"]
    with pytest.raises(CatalogIntegrityError):
        CatalogRepository(bad)


def test_standard_configuration_is_valid_and_priced_at_base(engine):
    view = engine.view(I5, [])
    assert view.valid
    assert view.total_price == view.base_price == 71900
    assert {"wheels_19_aero", "seats_standard", "paint_alpine_white"} <= set(view.options)


def test_unknown_model_raises(engine):
    with pytest.raises(UnknownModelError):
        engine.view("m3_wagon", [])


def test_requires_auto_adds_dependency_with_explanation(engine):
    res = add(engine, base(engine), "pkg_driving_assistant_pro")
    assert res.status == "applied"
    assert "pkg_parking_assistant" in res.configuration.options
    assert any(n.kind == "auto_added" and n.option_id == "pkg_parking_assistant" for n in res.notes)
    line = next(line for line in res.configuration.lines if line.id == "pkg_parking_assistant")
    assert line.status == "auto_added" and "Driving Assistant Professional" in line.reason


def test_unavailable_option_is_rejected_with_alternatives(engine):
    res = add(engine, base(engine), "tow_hitch", model="i4_edrive40")
    assert res.status == "rejected"
    assert res.error.code == "not_available"
    assert "BMW i5 Touring eDrive40" in res.error.alternatives
    assert "tow_hitch" not in res.configuration.options


def test_unknown_option_is_rejected(engine):
    res = add(engine, base(engine), "flux_capacitor")
    assert res.status == "rejected" and res.error.code == "unknown_option"


def test_dependency_unavailable_on_model(engine):
    # third_row needs rear_climate; both are X5 only, so check a model that lacks it
    res = add(engine, base(engine, "ix1_xdrive30"), "third_row", model="ix1_xdrive30")
    assert res.status == "rejected"


def test_group_replacement_by_direct_choice_is_silent(engine):
    res = add(engine, base(engine), "wheels_20_sport")
    assert res.status == "applied"
    assert "wheels_19_aero" not in res.configuration.options
    assert res.configuration.specs["electric_range_km"] == round(560 * 0.97)


def test_package_includes_items_at_no_extra_cost(engine):
    res = add(engine, base(engine), "pkg_travel_comfort")
    lines = {line.id: line for line in res.configuration.lines}
    assert lines["seats_comfort"].status == "included" and lines["seats_comfort"].price == 0
    assert res.configuration.total_price == 71900 + 2950


def test_choice_that_breaks_a_package_returns_conflict(engine):
    opts = add(engine, base(engine), "pkg_travel_comfort").configuration.options
    res = add(engine, opts, "seats_sport")
    assert res.status == "conflict"
    assert "pkg_travel_comfort" in res.conflict.option_ids
    assert res.configuration.options == opts  # nothing changed
    forced = add(engine, opts, "seats_sport", force=True)
    assert forced.status == "applied"
    assert "pkg_travel_comfort" not in forced.configuration.options
    assert "heated_steering" not in forced.configuration.options  # package contents go too
    assert engine.validate(I5, forced.configuration.options) == []


def test_two_packages_locking_the_same_group_conflict(engine):
    opts = add(engine, base(engine), "pkg_travel_comfort").configuration.options
    res = add(engine, opts, "pkg_m_sport")
    assert res.status == "conflict"
    assert [r.change for r in res.conflict.resolutions][-1] is None  # "keep" option offered


def test_explicit_exclusion_conflict(engine):
    opts = add(engine, base(engine), "panorama_roof").configuration.options
    res = add(engine, opts, "roof_rails")
    assert res.status == "conflict"
    assert "cannot be combined" in res.conflict.message


def test_requires_chain_through_package(engine):
    res = add(engine, base(engine), "wheels_21_m")
    assert res.status == "applied"
    assert {"pkg_m_sport", "seats_sport", "wheels_21_m"} <= set(res.configuration.options)
    assert engine.validate(I5, res.configuration.options) == []


def test_removing_a_dependency_asks_first(engine):
    opts = add(engine, base(engine), "pkg_driving_assistant_pro").configuration.options
    res = remove(engine, opts, "pkg_parking_assistant")
    assert res.status == "conflict"
    forced = remove(engine, opts, "pkg_parking_assistant", force=True)
    assert not {"pkg_parking_assistant", "pkg_driving_assistant_pro"} & set(forced.configuration.options)


def test_removing_package_item_points_to_package(engine):
    opts = add(engine, base(engine), "pkg_travel_comfort").configuration.options
    res = remove(engine, opts, "heated_steering")
    assert res.status == "conflict"
    assert res.conflict.resolutions[0].change.option_id == "pkg_travel_comfort"


def test_standard_group_item_cannot_be_removed(engine):
    res = remove(engine, base(engine), "wheels_19_aero")
    assert res.status == "rejected" and res.error.code == "not_removable"


def test_removing_group_choice_restores_standard(engine):
    opts = add(engine, base(engine), "seats_comfort").configuration.options
    res = remove(engine, opts, "seats_comfort")
    assert "seats_standard" in res.configuration.options


def test_validate_detects_invalid_sets(engine):
    codes = {i.code for i in engine.validate("i4_edrive40", ["tow_hitch", "wheels_21_m", "panorama_roof", "roof_rails",
                                                              "wheels_19_aero", "seats_standard", "paint_alpine_white"])}
    assert {"not_available", "dependency_missing", "excluded_combination", "group_conflict"} <= codes


def test_budget_overrun_suggests_savings(engine):
    opts = add(engine, base(engine), "audio_bw").configuration.options
    opts = add(engine, opts, "pkg_driving_assistant_pro").configuration.options
    opts = add(engine, opts, "pkg_travel_comfort").configuration.options
    view = engine.view(I5, opts, Requirements(budget_max=78000))
    assert view.budget.over_by == view.total_price - 78000 > 0
    assert view.savings[0].option_id == "audio_bw"
    # removing DA Pro's dependency would also remove DA Pro, so the saving includes both
    assert any(s.option_id == "pkg_parking_assistant" and s.saves == 1250 + 2100 for s in view.savings)


def test_switch_model_carries_compatible_choices(engine):
    opts = add(engine, base(engine), "audio_bw").configuration.options
    opts = add(engine, opts, "hud").configuration.options
    res = engine.switch_model("i4_edrive40", opts)
    assert "hud" in res.configuration.options
    assert "audio_bw" not in res.configuration.options
    assert any(n.kind == "dropped" and n.option_id == "audio_bw" for n in res.notes)
