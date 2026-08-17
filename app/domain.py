from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from statistics import mean, pstdev
from typing import Any

import numpy as np
import shap
from lime.lime_tabular import LimeTabularExplainer
from sklearn.ensemble import RandomForestRegressor


class Role(str, Enum):
    ANALYST = "ANALYST"
    PLANNER = "PLANNER"
    APPROVER = "APPROVER"
    ADMIN = "ADMIN"
    OBSERVER = "OBSERVER"


class InterventionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class DomainFailure(Exception):
    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message


@dataclass
class DemandObservation:
    id: str
    sku: str
    observed_on: str
    units_sold: int
    price: float
    promotion_active: bool
    created_at: str


@dataclass
class ForecastRun:
    id: str
    sku: str
    projected_units: float
    confidence: float
    model_version: str
    created_by: str
    created_at: str
    shap_contributions: dict[str, float]
    lime_explanations: list[dict[str, float | str]]


@dataclass
class Intervention:
    id: str
    forecast_run_id: str
    action_type: str
    status: InterventionStatus
    requested_by: str
    approved_by: str | None
    created_at: str
    updated_at: str


@dataclass
class AuditEvent:
    id: str
    forecast_run_id: str
    actor: str
    action: str
    detail: str
    created_at: str


class ForecastEngine:
    feature_names = ["day_index", "price", "promotion_active", "lag_units", "rolling_average"]

    def __init__(self) -> None:
        self.observations: dict[str, DemandObservation] = {}
        self.forecasts: dict[str, ForecastRun] = {}
        self.interventions: dict[str, Intervention] = {}
        self.audits: list[AuditEvent] = []

    def add_observation(self, actor: str, role: Role, observation_id: str, sku: str, observed_on: str, units_sold: int, price: float, promotion_active: bool) -> DemandObservation:
        self._allow(role, Role.ANALYST, Role.ADMIN)
        if not observation_id or len(observation_id) > 80 or not sku.strip():
            self._fail("validation", "observation id and sku are required")
        if observation_id in self.observations:
            self._fail("conflict", "observation id already exists")
        try:
            date.fromisoformat(observed_on)
        except ValueError:
            self._fail("validation", "observed_on must use ISO date format")
        if units_sold < 0 or price <= 0:
            self._fail("validation", "units_sold cannot be negative and price must be greater than zero")
        item = DemandObservation(observation_id, sku.strip().upper(), observed_on, units_sold, float(price), bool(promotion_active), self._now())
        self.observations[observation_id] = item
        return item

    def create_forecast(self, actor: str, role: Role, forecast_id: str, sku: str, forecast_on: str, price: float, promotion_active: bool) -> ForecastRun:
        self._allow(role, Role.ANALYST, Role.ADMIN)
        if not forecast_id or forecast_id in self.forecasts:
            self._fail("conflict" if forecast_id in self.forecasts else "validation", "forecast id must be unique and nonempty")
        if price <= 0:
            self._fail("validation", "forecast price must be greater than zero")
        try:
            target_day = date.fromisoformat(forecast_on)
        except ValueError:
            self._fail("validation", "forecast_on must use ISO date format")
        normalized_sku = sku.strip().upper()
        history = self._history(normalized_sku)
        if len(history) < 8:
            self._fail("validation", "at least eight historical observations are required for a forecast")
        features, labels = self._training_set(history)
        if len(labels) < 5:
            self._fail("validation", "forecast history does not yet produce enough model training rows")
        model = RandomForestRegressor(n_estimators=80, max_depth=5, random_state=42)
        model.fit(features, labels)
        row = self._feature_row(target_day, price, promotion_active, history[-1].units_sold, mean([item.units_sold for item in history[-3:]]))
        projected = max(0.0, float(model.predict([row])[0]))
        tree_predictions = [float(tree.predict([row])[0]) for tree in model.estimators_]
        dispersion = pstdev(tree_predictions) if len(tree_predictions) > 1 else 0.0
        confidence = round(max(0.2, min(0.98, 1 - (dispersion / max(projected, 1.0)))), 3)
        shap_values = shap.TreeExplainer(model).shap_values(np.array([row]))
        values = np.asarray(shap_values)
        if values.ndim == 2:
            values = values[0]
        contributions = {name: round(float(value), 4) for name, value in zip(self.feature_names, values, strict=True)}
        explainer = LimeTabularExplainer(np.array(features), feature_names=self.feature_names, mode="regression", random_state=42)
        local = explainer.explain_instance(np.array(row), model.predict, num_features=5)
        lime_rows = [{"feature": feature, "weight": round(float(weight), 4)} for feature, weight in local.as_list()]
        run = ForecastRun(forecast_id, normalized_sku, round(projected, 2), confidence, "random-forest-v1", actor, self._now(), contributions, lime_rows)
        self.forecasts[forecast_id] = run
        self._audit(actor, forecast_id, "forecast_created", f"Created forecast for {normalized_sku} with projected demand {run.projected_units}")
        return run

    def propose_intervention(self, actor: str, role: Role, intervention_id: str, forecast_run_id: str, action_type: str) -> Intervention:
        self._allow(role, Role.PLANNER, Role.ADMIN)
        if intervention_id in self.interventions:
            self._fail("conflict", "intervention id already exists")
        if forecast_run_id not in self.forecasts:
            self._fail("not_found", "forecast run was not found")
        if action_type not in {"increase_replenishment", "reduce_replenishment", "review_promotion"}:
            self._fail("validation", "intervention action type is not supported")
        item = Intervention(intervention_id, forecast_run_id, action_type, InterventionStatus.PROPOSED, actor, None, self._now(), self._now())
        self.interventions[intervention_id] = item
        self._audit(actor, forecast_run_id, "intervention_proposed", f"Proposed {action_type} intervention")
        return item

    def approve_intervention(self, actor: str, role: Role, intervention_id: str) -> Intervention:
        self._allow(role, Role.APPROVER, Role.ADMIN)
        item = self.interventions.get(intervention_id)
        if item is None:
            self._fail("not_found", "intervention was not found")
        if item.status is not InterventionStatus.PROPOSED:
            self._fail("conflict", "only a proposed intervention can be approved")
        item.status = InterventionStatus.APPROVED
        item.approved_by = actor
        item.updated_at = self._now()
        self._audit(actor, item.forecast_run_id, "intervention_approved", f"Approved {item.action_type} intervention")
        return item

    def seed_demo(self, actor: str, role: Role) -> dict[str, Any]:
        self._allow(role, Role.ANALYST, Role.ADMIN)
        if self.observations:
            self._fail("conflict", "demo observations can only seed an empty planning workspace")
        start = date(2026, 1, 1)
        for index in range(14):
            promo = index in {4, 5, 11}
            units = 42 + index * 2 + (12 if promo else 0) + (index % 3)
            self.add_observation(actor, role, f"OBS-{index + 1:03}", "DEMO-SKU", (start + timedelta(days=index)).isoformat(), units, 19.5 if promo else 22.0, promo)
        return {"observations": 14, "sku": "DEMO-SKU"}

    def snapshot(self) -> dict[str, Any]:
        return {
            "observations": [asdict(item) for item in sorted(self.observations.values(), key=lambda value: value.observed_on)],
            "forecasts": [asdict(item) for item in sorted(self.forecasts.values(), key=lambda value: value.created_at, reverse=True)],
            "interventions": [self._intervention_json(item) for item in sorted(self.interventions.values(), key=lambda value: value.updated_at, reverse=True)],
            "audit_events": [asdict(item) for item in reversed(self.audits)],
        }

    def _history(self, sku: str) -> list[DemandObservation]:
        return sorted((item for item in self.observations.values() if item.sku == sku), key=lambda value: value.observed_on)

    def _training_set(self, history: list[DemandObservation]) -> tuple[list[list[float]], list[float]]:
        features: list[list[float]] = []
        labels: list[float] = []
        for index in range(3, len(history)):
            target = history[index]
            previous = history[index - 1]
            rolling = mean([item.units_sold for item in history[index - 3:index]])
            features.append(self._feature_row(date.fromisoformat(target.observed_on), target.price, target.promotion_active, previous.units_sold, rolling))
            labels.append(float(target.units_sold))
        return features, labels

    @staticmethod
    def _feature_row(day: date, price: float, promotion_active: bool, lag_units: float, rolling_average: float) -> list[float]:
        return [float(day.toordinal()), float(price), 1.0 if promotion_active else 0.0, float(lag_units), float(rolling_average)]

    @staticmethod
    def _intervention_json(item: Intervention) -> dict[str, Any]:
        output = asdict(item)
        output["status"] = item.status.value
        return output

    def _audit(self, actor: str, forecast_run_id: str, action: str, detail: str) -> None:
        self.audits.append(AuditEvent(f"AUD-{len(self.audits) + 1:04}", forecast_run_id, actor, action, detail, self._now()))

    @staticmethod
    def _allow(role: Role, *allowed: Role) -> None:
        if role not in allowed:
            raise DomainFailure("authorization", "role is not permitted for this forecast action")

    @staticmethod
    def _fail(kind: str, message: str) -> None:
        raise DomainFailure(kind, message)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

