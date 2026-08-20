from datetime import date, timedelta

import pytest

from app.domain import DomainFailure, ForecastEngine, InterventionStatus, Role


def ready_engine() -> ForecastEngine:
    engine = ForecastEngine()
    start = date(2026, 1, 1)
    for index in range(12):
        engine.add_observation("analyst", Role.ANALYST, f"OBS-{index}", "SKU-1", (start + timedelta(days=index)).isoformat(), 35 + index + (10 if index in {4, 8} else 0), 20.0, index in {4, 8})
    return engine


def test_forecast_contains_shap_and_lime_evidence():
    engine = ready_engine()
    forecast = engine.create_forecast("analyst", Role.ANALYST, "FC-1001", "SKU-1", "2026-01-14", 20.0, False)
    assert forecast.projected_units >= 0
    assert set(forecast.shap_contributions) == set(engine.feature_names)
    assert len(forecast.lime_explanations) == 5
    assert engine.snapshot()["audit_events"][0]["action"] == "forecast_created"


def test_observer_cannot_add_observations_or_create_forecast():
    engine = ready_engine()
    with pytest.raises(DomainFailure, match="not permitted") as failure:
        engine.create_forecast("observer", Role.OBSERVER, "FC-1001", "SKU-1", "2026-01-14", 20.0, False)
    assert failure.value.kind == "authorization"


def test_forecast_requires_sufficient_history_and_valid_price():
    engine = ForecastEngine()
    with pytest.raises(DomainFailure) as low_history:
        engine.create_forecast("analyst", Role.ANALYST, "FC-1001", "SKU-1", "2026-01-14", 20.0, False)
    assert low_history.value.kind == "validation"
    engine = ready_engine()
    with pytest.raises(DomainFailure) as invalid_price:
        engine.create_forecast("analyst", Role.ANALYST, "FC-1001", "SKU-1", "2026-01-14", 0, False)
    assert invalid_price.value.kind == "validation"


def test_intervention_requires_planner_then_approver():
    engine = ready_engine()
    engine.create_forecast("analyst", Role.ANALYST, "FC-1001", "SKU-1", "2026-01-14", 20.0, False)
    proposed = engine.propose_intervention("planner", Role.PLANNER, "INT-1001", "FC-1001", "increase_replenishment")
    assert proposed.status is InterventionStatus.PROPOSED
    approved = engine.approve_intervention("approver", Role.APPROVER, "INT-1001")
    assert approved.status is InterventionStatus.APPROVED
    with pytest.raises(DomainFailure) as repeated:
        engine.approve_intervention("approver", Role.APPROVER, "INT-1001")
    assert repeated.value.kind == "conflict"


def test_approver_can_reject_proposed_intervention():
    engine = ready_engine()
    engine.create_forecast("analyst", Role.ANALYST, "FC-1001", "SKU-1", "2026-01-14", 20.0, False)
    engine.propose_intervention("planner", Role.PLANNER, "INT-1001", "FC-1001", "increase_replenishment")
    rejected = engine.reject_intervention("approver", Role.APPROVER, "INT-1001")
    assert rejected.status is InterventionStatus.REJECTED
    assert engine.snapshot()["audit_events"][0]["action"] == "intervention_rejected"
    with pytest.raises(DomainFailure) as repeated:
        engine.reject_intervention("approver", Role.APPROVER, "INT-1001")
    assert repeated.value.kind == "conflict"


def test_planner_cannot_approve_and_unknown_forecast_is_rejected():
    engine = ready_engine()
    with pytest.raises(DomainFailure) as missing:
        engine.propose_intervention("planner", Role.PLANNER, "INT-1001", "UNKNOWN", "increase_replenishment")
    assert missing.value.kind == "not_found"
    engine.create_forecast("analyst", Role.ANALYST, "FC-1001", "SKU-1", "2026-01-14", 20.0, False)
    engine.propose_intervention("planner", Role.PLANNER, "INT-1001", "FC-1001", "increase_replenishment")
    with pytest.raises(DomainFailure) as unauthorized:
        engine.approve_intervention("planner", Role.PLANNER, "INT-1001")
    assert unauthorized.value.kind == "authorization"
