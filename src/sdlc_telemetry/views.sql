-- One view per metric. Definitions are documented in docs/METRICS.md.

CREATE OR REPLACE VIEW v_adoption_weekly AS
SELECT date_trunc('week', ts) AS week,
       count(DISTINCT session_id) AS sessions,
       count(*) AS prompts
FROM prompts
GROUP BY 1;

CREATE OR REPLACE VIEW v_component_usage AS
WITH pre AS (
    SELECT tool_use_id, ts FROM hook_events WHERE event = 'PreToolUse' AND tool_use_id <> ''
), post AS (
    SELECT * FROM hook_events
    WHERE event IN ('PostToolUse', 'PostToolUseFailure') AND tool IN ('Skill', 'Task', 'Agent')
)
SELECT post.tool AS kind,
       post.name AS component,
       count(*) AS invocations,
       count(*) FILTER (WHERE post.status = 'fail') AS failures,
       round(avg((post.status = 'fail')::INT), 3) AS failure_rate,
       round(avg(date_diff('millisecond', pre.ts, post.ts) / 1000.0), 2) AS avg_seconds
FROM post LEFT JOIN pre USING (tool_use_id)
GROUP BY 1, 2;

CREATE OR REPLACE VIEW v_stage_quality AS
WITH ranked AS (
    SELECT stage, status,
           row_number() OVER (PARTITION BY session_id, stage ORDER BY ts) AS rn
    FROM hook_events
    WHERE tool = 'Bash' AND stage IN ('test', 'lint', 'build')
      AND event IN ('PostToolUse', 'PostToolUseFailure')
)
SELECT stage,
       count(*) AS runs,
       round(avg((status = 'ok')::INT), 3) AS pass_rate,
       round(avg(CASE WHEN rn = 1 THEN (status = 'ok')::INT END), 3) AS first_pass_rate
FROM ranked
GROUP BY 1;

CREATE OR REPLACE VIEW v_task_cycle AS
SELECT s.session_id, p.ts AS prompt_ts, s.ts AS stop_ts,
       date_diff('second', p.ts, s.ts) AS seconds
FROM (SELECT * FROM hook_events WHERE event = 'Stop') s
ASOF JOIN (SELECT session_id, ts FROM hook_events WHERE event = 'UserPromptSubmit') p
  ON s.session_id = p.session_id AND s.ts >= p.ts;

CREATE OR REPLACE VIEW v_guardrail_blocks AS
SELECT rule, count(*) AS blocks
FROM hook_events
WHERE event = 'GuardrailBlock'
GROUP BY 1;

CREATE OR REPLACE VIEW v_cost_session AS
WITH priced AS (
    SELECT u.*, p.input_per_m, p.output_per_m, p.cache_read_per_m, p.cache_write_per_m,
           row_number() OVER (PARTITION BY u.msg_id ORDER BY length(p.prefix) DESC) AS rk
    FROM api_usage u JOIN pricing p ON starts_with(u.model, p.prefix)
)
SELECT session_id,
       min(ts) AS started,
       sum(input_tokens) AS input_tokens,
       sum(output_tokens) AS output_tokens,
       sum(cache_read) AS cache_read,
       sum(cache_create) AS cache_create,
       round(sum(cache_read) * 1.0
             / nullif(sum(input_tokens + cache_read + cache_create), 0), 3) AS cache_hit_rate,
       round(sum((input_tokens * input_per_m + output_tokens * output_per_m
                  + cache_read * cache_read_per_m + cache_create * cache_write_per_m)
                 / 1e6), 4) AS cost_usd
FROM priced
WHERE rk = 1
GROUP BY 1;

CREATE OR REPLACE VIEW v_pr_compare AS
SELECT CASE WHEN ai_assisted THEN 'ai_assisted' ELSE 'baseline' END AS cohort,
       count(*) AS prs,
       round(median(date_diff('minute', created_at, merged_at) / 60.0), 2) AS median_cycle_hours,
       round(avg(review_rounds), 2) AS avg_review_rounds,
       round(avg(ci_first_pass::INT), 3) AS ci_first_pass_rate,
       round(avg(additions + deletions), 0) AS avg_lines_changed
FROM prs
WHERE merged_at IS NOT NULL
GROUP BY ai_assisted;

-- Proxy for rework: share of commits (older than 14 days) whose files were touched
-- again by a later commit within 14 days.
CREATE OR REPLACE VIEW v_rework AS
WITH f AS (SELECT sha, ts, unnest(files) AS file FROM commits)
SELECT CASE WHEN ai_assisted THEN 'ai_assisted' ELSE 'baseline' END AS cohort,
       count(*) AS commits,
       round(avg(reworked::INT), 3) AS rework_rate
FROM (
    SELECT c.sha, c.ai_assisted,
           EXISTS (
               SELECT 1 FROM f a JOIN f b ON a.file = b.file
               WHERE a.sha = c.sha AND b.sha <> c.sha
                 AND b.ts > c.ts AND b.ts <= c.ts + INTERVAL 14 DAY
           ) AS reworked
    FROM commits c
    WHERE c.ts <= (current_timestamp AT TIME ZONE 'UTC') - INTERVAL 14 DAY
      AND len(c.files) > 0
) GROUP BY ai_assisted;
