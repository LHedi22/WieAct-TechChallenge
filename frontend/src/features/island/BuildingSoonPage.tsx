import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";
import { TopBar } from "@/app/TopBar";
import { Mascot, PixelPanel } from "@/components";

/** Where Confirm leads until the buildings open (M4: Quiz Hall + Socratic Tutor). No AI call. */
export function BuildingSoonPage() {
  const { worldId = "", courseId = "", building = "" } = useParams();
  const { t } = useTranslation("island");
  const { t: tc } = useTranslation();
  return (
    <div className="flex min-h-screen flex-col">
      <TopBar worldId={worldId} />
      <main className="mx-auto flex max-w-lg flex-1 items-center px-4">
        <PixelPanel className="flex flex-col items-center gap-4 p-6 text-center">
          <Mascot pose="thinking" scale={3} />
          <h1 className="text-h2">{tc(`buildings.${building}`)}</h1>
          <p>{t("soon.body")}</p>
          <Link
            to={`/worlds/${worldId}/courses/${courseId}`}
            className="font-semibold text-primary underline"
          >
            {t("soon.back")}
          </Link>
        </PixelPanel>
      </main>
    </div>
  );
}
