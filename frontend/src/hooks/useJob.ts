import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type JobView } from "@/api/client";
import type { Stage } from "@/components";

export const JOB_POLL_MS = 1500; // the platform has no streaming: poll (CLAUDE.md rule 4)
const TERMINAL = new Set<JobView["status"]>(["done", "failed", "cancelled"]);

export function isTerminal(status: JobView["status"] | undefined): boolean {
  return status !== undefined && TERMINAL.has(status);
}

/** Map the job's stage keys to done / in progress / next for LoadingStages. */
export function stagesOf(job: JobView | undefined): Stage[] {
  if (!job) return [];
  const current = job.stage ? job.stages.indexOf(job.stage) : -1;
  return job.stages.map((key, i): Stage => {
    if (job.status === "done" || i < current) return { key, state: "done" };
    return { key, state: i === current ? "inProgress" : "next" };
  });
}

/** Polls GET /api/jobs/{id} every 1.5 s until the job ends. */
export function useJob(jobId: string | null) {
  const qc = useQueryClient();
  const query = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => api.job(jobId as string),
    enabled: !!jobId,
    refetchInterval: (q) => (isTerminal(q.state.data?.status) ? false : JOB_POLL_MS),
  });
  const cancel = useMutation({
    mutationFn: () => api.cancelJob(jobId as string),
    onSuccess: (job) => qc.setQueryData(["job", jobId], job),
  });
  const job = query.data;
  return {
    job,
    status: job?.status,
    stages: stagesOf(job),
    queuePosition: job?.queue_position ?? null,
    etaS: job?.eta_s ?? null,
    waitingReason: job?.waiting_reason ?? null,
    quickMode: job?.quick_mode ?? false,
    error: job?.error ?? (query.error ? "errors.network" : null),
    isTerminal: isTerminal(job?.status),
    cancel: cancel.mutate,
    cancelError: cancel.error,
    cancelling: cancel.isPending,
  };
}
