import { useTranslation } from "react-i18next";
import { cx } from "@/components/cx";
import { useNumberFormat } from "@/components/useNumberFormat";

/** Upload kinds the backend accepts (app/rag/parsing.py KINDS). */
export const ACCEPT = ".pdf,.pptx,.docx,.txt,.md,.png,.jpg,.jpeg,.webp";

export function kindOf(filename: string): string {
  const ext = filename.split(".").pop()?.toLowerCase() ?? "";
  if (["png", "jpg", "jpeg", "webp"].includes(ext)) return "image";
  if (ext === "md") return "txt";
  return ext;
}

export function useFileSize() {
  const { t } = useTranslation("worlds");
  const nf = useNumberFormat();
  return (bytes: number) =>
    bytes < 1024 * 1024
      ? t("size.kb", { n: nf.format(Math.max(1, Math.round(bytes / 1024))) })
      : t("size.mb", { n: nf.format(Math.round((bytes / 1024 / 1024) * 10) / 10) });
}

// Tinted chips per island accent (tints via opacity; the text stays ink for contrast).
const ACCENT_CHIP: Record<string, string> = {
  "island-1": "bg-island-1/15",
  "island-2": "bg-island-2/20",
  "island-3": "bg-island-3/20",
  "island-4": "bg-island-4/20",
  "island-5": "bg-island-5/15",
  "island-6": "bg-island-6/15",
};

export function accentChip(colorKey: string): string {
  return cx("text-ink", ACCENT_CHIP[colorKey] ?? "bg-sand");
}
