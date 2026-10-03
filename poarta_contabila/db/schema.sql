-- Poarta Primară domain store (00_LAW A1). Not a ledger: no chart of accounts,
-- journal or trial balance lives here (invariant 1). Idempotency keys from
-- IDEMPOTENCY.md are unique constraints. Idempotent: safe to run on every boot.

CREATE SCHEMA IF NOT EXISTS domain;

CREATE TABLE IF NOT EXISTS domain.jobs (
    job_id       text PRIMARY KEY,
    tenant_cui   text NOT NULL,
    source_hash  text NOT NULL,
    period       text NOT NULL,
    status       text NOT NULL,
    body         jsonb NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT jobs_source_once UNIQUE (tenant_cui, source_hash)
);

CREATE TABLE IF NOT EXISTS domain.canonical (
    job_id  text PRIMARY KEY REFERENCES domain.jobs (job_id),
    body    jsonb NOT NULL
);

CREATE TABLE IF NOT EXISTS domain.extracts (
    source_hash  text NOT NULL,
    backend      text NOT NULL,
    meta         jsonb NOT NULL,
    PRIMARY KEY (source_hash, backend)
);
-- WP-21: the bucket prefix holding {prefix}/normalized/ (EXTRACT.md) for that source.
ALTER TABLE domain.extracts ADD COLUMN IF NOT EXISTS prefix text;

CREATE TABLE IF NOT EXISTS domain.packages (
    export_key  text PRIMARY KEY,           -- {module_id}:{job_id}:{schema_version}
    job_id      text NOT NULL REFERENCES domain.jobs (job_id),
    module_id   text NOT NULL,
    bucket_key  text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS domain.recon_verdicts (
    job_id            text NOT NULL REFERENCES domain.jobs (job_id),
    stage             text NOT NULL CHECK (stage IN ('pre', 'post')),
    sink_snapshot_id  text NOT NULL,
    body              jsonb NOT NULL,
    PRIMARY KEY (job_id, stage, sink_snapshot_id)
);

CREATE TABLE IF NOT EXISTS domain.hitl_resumes (
    thread_id     text NOT NULL,
    interrupt_id  text NOT NULL,
    kind          text NOT NULL,
    body          jsonb NOT NULL,
    actor         text NOT NULL,
    at            timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (thread_id, interrupt_id)
);

CREATE TABLE IF NOT EXISTS domain.close_runs (
    cui                text NOT NULL,
    period             text NOT NULL,
    expected_set_hash  text,
    body               jsonb NOT NULL,
    PRIMARY KEY (cui, period)
);

CREATE TABLE IF NOT EXISTS domain.close_snapshots (
    snapshot_id  text PRIMARY KEY,
    cui          text NOT NULL,
    period       text NOT NULL,
    body         jsonb NOT NULL,
    captured_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS domain.control_runs (
    cui          text NOT NULL,
    period       text NOT NULL,
    control_id   text NOT NULL,
    snapshot_id  text NOT NULL,
    body         jsonb NOT NULL,
    PRIMARY KEY (cui, period, control_id, snapshot_id)
);

CREATE TABLE IF NOT EXISTS domain.filing_items (
    cui          text NOT NULL,
    period       text NOT NULL,
    filing_id    text NOT NULL,
    state        text NOT NULL DEFAULT 'open' CHECK (state IN ('open', 'filed')),
    receipt_key  text,
    PRIMARY KEY (cui, period, filing_id),
    CONSTRAINT filed_needs_receipt CHECK (state = 'open' OR receipt_key IS NOT NULL)
);
ALTER TABLE domain.filing_items ADD COLUMN IF NOT EXISTS submitted_by text;

CREATE TABLE IF NOT EXISTS domain.codit (
    cui     text NOT NULL,
    period  text NOT NULL,
    body    jsonb NOT NULL,
    hash    text NOT NULL,
    PRIMARY KEY (cui, period)
);

-- Jev answers (ARCHITECTURE §12): validated JSON only, so a replay or a repeated question
-- is not paid for twice. A suggestion store, not books.
CREATE TABLE IF NOT EXISTS domain.jev_answers (
    pack        text NOT NULL,
    input_hash  text NOT NULL,              -- sha256 of {pack, version, input}
    body        jsonb NOT NULL,
    at          timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (pack, input_hash)
);

-- Lane A (per client)
CREATE TABLE IF NOT EXISTS domain.maps (
    cui    text NOT NULL,
    kind   text NOT NULL,                   -- partner_analytic | name_to_cui | iban_to_cui | ...
    key    text NOT NULL,
    value  text NOT NULL,
    PRIMARY KEY (cui, kind, key)
);

CREATE TABLE IF NOT EXISTS domain.explained_rules (
    cui      text NOT NULL,
    rule_id  text NOT NULL,
    version  integer NOT NULL,
    body     jsonb NOT NULL,
    PRIMARY KEY (cui, rule_id, version)
);

-- WP-06 Windows agent. A backup label is {cui}:{folder}:{utc}; a restore is refused
-- when the label's tenant differs. Snapshots are what SAGA showed the agent (the eye).
CREATE TABLE IF NOT EXISTS domain.agent_backups (
    label       text PRIMARY KEY,
    tenant_cui  text NOT NULL,
    folder      text NOT NULL,
    taken_at    timestamptz NOT NULL,
    acked_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS domain.agent_snapshots (
    snapshot_id  text PRIMARY KEY,           -- sha256 of the body
    tenant_cui   text NOT NULL,
    folder       text NOT NULL,
    taken_at     timestamptz NOT NULL,
    body         jsonb NOT NULL,
    received_at  timestamptz NOT NULL DEFAULT now()
);

-- Runtime: tenants (what the SAGA mouth needs) and the files that witness their books.
CREATE TABLE IF NOT EXISTS domain.tenants (
    cui         text PRIMARY KEY,
    body        jsonb NOT NULL,
    updated_at  timestamptz NOT NULL DEFAULT now()
);

-- Model roles (00_LAW §3.5): what each role was (or would be, MODEL_CALLS=dry) sent.
CREATE TABLE IF NOT EXISTS domain.model_calls (
    call_id     text PRIMARY KEY,
    role_id     text NOT NULL,
    at          text NOT NULL,               -- UTC, YYYY-MM-DDTHH:MM:SSZ
    body        jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS model_calls_role_at ON domain.model_calls (role_id, at);

-- WP-33: every answer a person submits; insert-only (no code path updates or deletes a row)
CREATE TABLE IF NOT EXISTS domain.answers (
    seq         bigserial PRIMARY KEY,
    answer_id   text NOT NULL UNIQUE,
    at          text NOT NULL,               -- UTC, microseconds
    tenant_cui  text,
    thread_id   text NOT NULL,
    body        jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS answers_tenant ON domain.answers (tenant_cui, seq);
CREATE INDEX IF NOT EXISTS answers_thread ON domain.answers (thread_id, seq);

CREATE TABLE IF NOT EXISTS domain.sink_exports (
    export_id   text PRIMARY KEY,            -- {kind}:{sha256 of the file}
    tenant_cui  text NOT NULL,
    kind        text NOT NULL CHECK (kind IN ('rj', 'balanta', 'spv_register',
                                       'jurnal_cumparari', 'jurnal_vanzari')),
    product     text,
    body        jsonb NOT NULL
);

-- WP-42: synthetic statements waiting for model quota (00_LAW §8 A5); read again from
-- not_before on. One row per (tenant, PDF).
CREATE TABLE IF NOT EXISTS domain.reading_waits (
    wait_id     text PRIMARY KEY,            -- {cui}:{sha256 of the PDF}
    tenant_cui  text NOT NULL,
    status      text NOT NULL CHECK (status IN ('waiting', 'read', 'refused', 'skipped')),
    not_before  text NOT NULL,               -- UTC ISO
    body        jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS reading_waits_due ON domain.reading_waits (status, not_before);
-- WP-42 → WP-43: a parked statement may be set aside by a person.
ALTER TABLE domain.reading_waits DROP CONSTRAINT IF EXISTS reading_waits_status_check;
ALTER TABLE domain.reading_waits ADD CONSTRAINT reading_waits_status_check
    CHECK (status IN ('waiting', 'read', 'refused', 'skipped'));

-- WP-43: what an operator chose when every model tier was spent (00_LAW §8 A6); insert-only.
CREATE TABLE IF NOT EXISTS domain.reading_choices (
    seq        bigserial PRIMARY KEY,
    choice_id  text NOT NULL UNIQUE,
    day        text NOT NULL,                -- the Pacific date it holds for
    body       jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS reading_choices_day ON domain.reading_choices (day, seq);

-- WP-53 (00_LAW §8 A7): OpenRouter provider data policies, read daily; one row per provider
CREATE TABLE IF NOT EXISTS domain.provider_policies (
    slug  text PRIMARY KEY,
    body  jsonb NOT NULL
);

-- WP-53: the operator's choice for a role no approved pin passes (latest holds)
CREATE TABLE IF NOT EXISTS domain.model_role_choices (
    seq      bigserial PRIMARY KEY,
    role_id  text NOT NULL,
    body     jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS model_role_choices_role ON domain.model_role_choices (role_id, seq);
