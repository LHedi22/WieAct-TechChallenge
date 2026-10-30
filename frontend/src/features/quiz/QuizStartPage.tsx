import { useMutation } from "@tanstack/react-query";
import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api } from "@/api/client";
import { Sprite } from "@/components";
import { JobProgress } from "@/features/jobs/JobProgress";
import { useOnce } from "@/hooks/useOnce";
import { useWisdomTip } from "@/features/wisdom/useWisdomTip";
import { ErrorBanner } from "@/features/worlds/parts";

/** …/quiz/new?chapter&level — a shared set opens at once; a new one is written as a job first. */
export function QuizStartPage() {
  const { worldId = "", courseId = "" } = useParams();
  const [params] = useSearchParams();
  const chapter = params.get("chapter") ?? "";
  const level = params.get("level") ?? "intermediate";
  const { t } = useTranslation("quiz");
  const navigate = useNavigate();
  const base = `/worlds/${worldId}/courses/${courseId}/quiz`;

  const start = useMutation({
    mutationFn: () => api.quizStart(chapter, level),
    onSuccess: (s) => s.attempt_id && void navigate(`${base}/${s.attempt_id}`, { replace: true }),
  });
  const fromJob = useMutation({
    mutationFn: (jobId: string) => api.quizFromJob(jobId),
    onSuccess: (a) => void navigate(`${base}/${a.id}`, { replace: true }),
  });
  const { mutate } = start;
  useOnce(mutate);
  const jobId = start.data?.job_id;
  const tip = useWisdomTip(worldId, courseId);

  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col gap-6 bg-whitewash px-4 py-8">
      <header className="flex items-center gap-3">
        <Sprite name="quizHall" scale={2} />
        <div>
          <h1 className="text-h3">{t("common:buildings.quiz_hall")}</h1>
          <p className="text-small text-ink/70">{t(`common:chip.${level}`)}</p>
        </div>
      </header>
      <h2 className="text-h1">{t("building")}</h2>
      <ErrorBanner error={start.error ?? fromJob.error} />
      {jobId && (
        <JobProgress jobId={jobId} tip={tip}>
          {() => <OpenWhenDone jobId={jobId} open={fromJob.mutate} started={fromJob.isPending} />}
        </JobProgress>
      )}
    </main>
  );
}

function OpenWhenDone({
  jobId,
  open,
  started,
}: {
  jobId: string;
  open: (jobId: string) => void;
  started: boolean;
}) {
  useEffect(() => {
    if (!started) open(jobId);
  }, [jobId, open, started]);
  return null;
}
