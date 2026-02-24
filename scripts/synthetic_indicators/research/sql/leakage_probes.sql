-- Leakage probe snippets for canonical dataset table/view.
-- Replace :DATASET_TABLE with your temp table name if needed.

-- 1) Timestamp invariant check (future leakage)
select
  count(*) as total_rows,
  count(*) filter (where source_time is not null and source_time > decision_deadline) as invalid_source_rows
from :DATASET_TABLE;

-- 2) Coverage by pair/config
select
  pair,
  config_id,
  count(*) as rows,
  min(bucket_time) as min_bucket,
  max(bucket_time) as max_bucket
from :DATASET_TABLE
group by pair, config_id
order by pair, config_id;

-- 3) Outcome balance sanity
select
  pair,
  config_id,
  outcome,
  count(*) as n
from :DATASET_TABLE
group by pair, config_id, outcome
order by pair, config_id, outcome;
