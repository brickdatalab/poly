import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const supabaseUrl = Deno.env.get("SUPABASE_URL")!;
const supabaseServiceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;

Deno.serve(async (req: Request) => {
  // Only accept POST requests.
  if (req.method !== "POST") {
    return new Response(JSON.stringify({ error: "Method not allowed" }), {
      status: 405,
      headers: { "Content-Type": "application/json" },
    });
  }

  const supabase = createClient(supabaseUrl, supabaseServiceKey, {
    db: { schema: "indicators" },
  });

  let jobsProcessed = 0;
  let jobsFailed = 0;
  const errors: string[] = [];

  try {
    // Fetch pending jobs with row-level locking using indicators schema.
    const { data: jobs, error: fetchError } = await supabase.rpc(
      "get_pending_indicator_jobs",
      { batch_size: 10 },
    );

    if (fetchError) {
      throw new Error(`Failed to fetch jobs: ${fetchError.message}`);
    }

    if (!jobs || jobs.length === 0) {
      return new Response(JSON.stringify({
        jobs_processed: 0,
        jobs_failed: 0,
        message: "No pending jobs",
      }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }

    // Process each job.
    for (const job of jobs) {
      try {
        // For non-1m timeframes, rollup OHLCV first.
        if (job.timeframe !== "1m") {
          const { error: rollupError } = await supabase.rpc(
            "fn_rollup_ohlcv",
            {
              p_pair: job.pair,
              p_timeframe: job.timeframe,
              p_bucket_time: job.bucket_time,
            },
          );

          if (rollupError) {
            throw new Error(`Rollup failed: ${rollupError.message}`);
          }
        }

        // Call the compute function (job is already marked as running by get_pending_indicator_jobs).
        const { error: computeError } = await supabase.rpc(
          "fn_compute_all_indicators",
          {
            p_pair: job.pair,
            p_bucket_time: job.bucket_time,
            p_timeframe: job.timeframe,
            p_triggered_by: "edge-worker",
          },
        );

        if (computeError) {
          throw new Error(computeError.message);
        }

        // Mark job as done.
        await supabase
          .from("job_queue")
          .update({ status: "done", completed_at: new Date().toISOString() })
          .eq("id", job.id);

        jobsProcessed++;
      } catch (jobError) {
        // Mark job as failed and log error.
        const errorMsg = jobError instanceof Error
          ? jobError.message
          : String(jobError);
        errors.push(`Job ${job.id}: ${errorMsg}`);

        await supabase
          .from("job_queue")
          .update({ status: "failed", completed_at: new Date().toISOString() })
          .eq("id", job.id);

        // Log to computation_log.
        await supabase
          .from("computation_log")
          .insert({
            pair: job.pair,
            bucket_time: job.bucket_time,
            timeframe: job.timeframe,
            status: "error",
            error_message: errorMsg,
            triggered_by: "edge-worker",
          });

        jobsFailed++;
      }
    }

    return new Response(JSON.stringify({
      jobs_processed: jobsProcessed,
      jobs_failed: jobsFailed,
      errors: errors.length > 0 ? errors : undefined,
    }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  } catch (error) {
    const errorMsg = error instanceof Error ? error.message : String(error);
    return new Response(JSON.stringify({
      error: errorMsg,
      jobs_processed: jobsProcessed,
      jobs_failed: jobsFailed,
    }), {
      status: 500,
      headers: { "Content-Type": "application/json" },
    });
  }
});

