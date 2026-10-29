import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "@/api/client";
import { TopBar } from "@/app/TopBar";
import { PixelPanel } from "@/components";
import { ErrorBanner, WorldSummaryBar } from "./parts";
import { UploadStep } from "./UploadStep";

/** /worlds/:worldId/upload — add files to an existing world (the wizard's upload step). */
export function AddMaterialPage() {
  const { worldId = "" } = useParams();
  const { t } = useTranslation("worlds");
  const navigate = useNavigate();
  const world = useQuery({ queryKey: ["world", worldId], queryFn: () => api.world(worldId) });
  return (
    <div className="flex min-h-screen flex-col">
      <TopBar worldId={worldId} />
      <main className="mx-auto flex w-full max-w-screen-lg flex-col gap-4 px-4 py-6 sm:px-8">
        <h1 className="text-h1">{t("steps.upload")}</h1>
        <ErrorBanner error={world.error} />
        {world.data && (
          <PixelPanel className="flex flex-col gap-4">
            <WorldSummaryBar name={world.data.name} courses={world.data.courses} />
            <UploadStep
              world={world.data}
              onBuild={() => void navigate(`/worlds/${worldId}/indexing`)}
            />
          </PixelPanel>
        )}
      </main>
    </div>
  );
}
