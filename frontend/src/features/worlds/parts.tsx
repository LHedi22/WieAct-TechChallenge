import { useMutation } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { api, type ApiError } from "@/api/client";
import { Banner, Bidi, Input, PixelButton, PixelPanel, Sprite } from "@/components";
import { cx } from "@/components/cx";
import { accentChip, kindOf } from "./util";

const BADGE: Record<string, string> = {
  pdf: "bg-terracotta-ink",
  pptx: "bg-terracotta",
  docx: "bg-primary",
  image: "bg-olive-ink",
  txt: "bg-ink",
};

/** The small coloured file-type tile ("PDF", "PPTX"…) from mockup 04. */
export function FileBadge({ filename }: { filename: string }) {
  const kind = kindOf(filename);
  const label = (filename.split(".").pop() ?? "").toUpperCase().slice(0, 4);
  return (
    <span
      aria-hidden
      className={cx(
        "inline-flex h-10 w-12 shrink-0 items-center justify-center rounded-pixel-step text-small font-semibold text-white",
        BADGE[kind] ?? "bg-ink",
      )}
    >
      {label}
    </span>
  );
}

/** "Join a world" card: code input → POST /api/worlds/join → the world's indexing screen. */
export function JoinCard({ initialCode = "" }: { initialCode?: string }) {
  const { t } = useTranslation("worlds");
  const { t: tc } = useTranslation();
  const navigate = useNavigate();
  const [code, setCode] = useState(initialCode);
  const join = useMutation({
    mutationFn: (c: string) => api.joinWorld(c),
    onSuccess: (world) => void navigate(`/worlds/${world.id}`),
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (code.trim()) join.mutate(code.trim());
  };
  return (
    <PixelPanel className="flex flex-col gap-4">
      <div className="flex items-start gap-3">
        <Sprite name="blueDoor" scale={3} />
        <div>
          <h2 className="text-h3">{t("join.title")}</h2>
          <p className="text-small text-ink/70">{t("join.subtitle")}</p>
        </div>
      </div>
      <form onSubmit={submit} className="flex items-end gap-2">
        <Input
          code
          className="min-w-0 flex-1"
          label={t("join.label")}
          placeholder={t("join.placeholder")}
          value={code}
          onChange={(e) => setCode(e.target.value)}
          autoComplete="off"
          spellCheck={false}
          error={join.error ? tc((join.error as ApiError).key) : undefined}
        />
        <PixelButton type="submit" disabled={join.isPending || !code.trim()}>
          {t("join.submit")}
        </PixelButton>
      </form>
    </PixelPanel>
  );
}

/** Error banner for a failed mutation/query (the message is always an i18n key). */
export function ErrorBanner({ error }: { error: unknown }) {
  const { t } = useTranslation();
  if (!error) return null;
  return <Banner kind="error">{t((error as ApiError).key ?? "errors.unexpected")}</Banner>;
}

/** World name + course chips summary bar (mockup 04, above the upload area). */
export function WorldSummaryBar({
  name,
  courses,
  onEdit,
}: {
  name: string;
  courses: { id: string; name: string; color_key: string }[];
  onEdit?: () => void;
}) {
  const { t } = useTranslation("worlds");
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-soft border-2 border-sand bg-white px-4 py-3">
      <span>
        <span className="text-ink/70">{t("summary.world")} </span>
        <Bidi className="font-semibold">{name}</Bidi>
      </span>
      <span className="text-ink/70">{t("summary.courses")}</span>
      <ul className="flex flex-wrap gap-2">
        {courses.map((c) => (
          <li
            key={c.id}
            className={cx(
              "rounded-pixel-step px-2 py-0.5 text-small font-semibold",
              accentChip(c.color_key),
            )}
          >
            <Bidi>{c.name}</Bidi>
          </li>
        ))}
      </ul>
      {onEdit && (
        <button
          type="button"
          onClick={onEdit}
          className="ms-auto font-semibold text-primary underline"
        >
          {t("summary.edit")}
        </button>
      )}
    </div>
  );
}
