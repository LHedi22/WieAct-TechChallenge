import { useTranslation } from "react-i18next";
import { Chip } from "./Chip";

/** Labels class content that a test model (the mock or local Ollama) wrote, not the platform
 * (audit F-OFF-1). Production only ever serves platform-made content, so this never shows there. */
export function TestDataChip({ madeBy }: { madeBy?: string | null }) {
  const { t } = useTranslation("common");
  if (!madeBy || madeBy === "cloud") return null;
  return (
    <Chip kind="cost" className="self-start">
      {t("testData", { provider: madeBy })}
    </Chip>
  );
}
