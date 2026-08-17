CREATE TABLE demand_observations (
  id VARCHAR(80) PRIMARY KEY,
  sku VARCHAR(80) NOT NULL,
  observed_on DATE NOT NULL,
  units_sold INT NOT NULL,
  price DECIMAL(12,2) NOT NULL,
  promotion_active BOOLEAN NOT NULL,
  created_at TIMESTAMP NOT NULL
);

CREATE TABLE forecast_runs (
  id VARCHAR(80) PRIMARY KEY,
  sku VARCHAR(80) NOT NULL,
  projected_units DECIMAL(14,3) NOT NULL,
  confidence DECIMAL(5,4) NOT NULL,
  model_version VARCHAR(80) NOT NULL,
  created_by VARCHAR(120) NOT NULL,
  created_at TIMESTAMP NOT NULL
);

CREATE TABLE forecast_interventions (
  id VARCHAR(80) PRIMARY KEY,
  forecast_run_id VARCHAR(80) NOT NULL,
  action_type VARCHAR(80) NOT NULL,
  status VARCHAR(30) NOT NULL,
  requested_by VARCHAR(120) NOT NULL,
  approved_by VARCHAR(120) NULL,
  created_at TIMESTAMP NOT NULL,
  updated_at TIMESTAMP NOT NULL
);

CREATE TABLE forecast_audit_events (
  id VARCHAR(80) PRIMARY KEY,
  forecast_run_id VARCHAR(80) NOT NULL,
  actor VARCHAR(120) NOT NULL,
  action VARCHAR(80) NOT NULL,
  detail VARCHAR(500) NOT NULL,
  created_at TIMESTAMP NOT NULL
);

