import { useMutation } from "@tanstack/react-query";
import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "@/api/client";
import { Mascot } from "@/components";
import { ErrorBanner, JoinCard } from "./parts";

/** /join/:code — the invite link: joins, then opens the world (its indexing screen until M3). */
export function JoinPage() {
  const { code = "" } = useParams();
  const { t } = useTranslation("worlds");
  const navigate = useNavigate();
  const join = useMutation({
    mutationFn: () => api.joinWorld(code),
    onSuccess: (world) => void navigate(`/worlds/${world.id}`, { replace: true }),
  });
  const { mutate } = join;
  useEffect(() => mutate(), [mutate]);

  return (
    <main className="mx-auto flex max-w-md flex-col items-center gap-5 px-4 py-12 text-center">
      <Mascot pose="waving" scale={4} />
      {join.isError ? (
        <div className="flex w-full flex-col gap-4 text-start">
          <ErrorBanner error={join.error} />
          <JoinCard initialCode={code} />
        </div>
      ) : (
        <p className="text-h3" aria-live="polite">
          {t("join.joining", { code })}
        </p>
      )}
    </main>
  );
}
