import { useQuery } from "@tanstack/react-query";
import { useId, useRef, useState, type DragEvent } from "react";
import { useTranslation } from "react-i18next";
import { api, ApiError, type DocumentOut, type IndexingOut, type WorldOut } from "@/api/client";
import { Bidi, Mascot, PixelButton, ProgressBar } from "@/components";
import { cx } from "@/components/cx";
import { JOB_POLL_MS } from "@/hooks/useJob";
import { useSystemStatus } from "@/hooks/useSystemStatus";
import { FileBadge } from "./parts";
import { ACCEPT, accentChip, kindOf, useFileSize } from "./util";

interface Item {
  key: string;
  filename: string;
  size: number;
  chapterId: string;
  courseId: string;
  state: "uploading" | "uploaded" | "error";
  doc?: DocumentOut;
  reused?: boolean;
  errorKey?: string;
}

const TYPE_KEYS = ["pdf", "slides", "word", "images", "text"] as const;
const SUPPORTED = new Set(["pdf", "pptx", "docx", "txt", "image"]);

/** Step 4 of the create wizard: files per chapter, uploaded in parallel, each with its state. */
export function UploadStep({ world, onBuild }: { world: WorldOut; onBuild: () => void }) {
  const { t } = useTranslation("worlds");
  const { t: tc } = useTranslation();
  const size = useFileSize();
  const maxMb = useSystemStatus().data?.upload_max_mb ?? 50;
  const [courseId, setCourseId] = useState(world.courses[0]?.id ?? "");
  const course = world.courses.find((c) => c.id === courseId) ?? world.courses[0];
  const [chapterId, setChapterId] = useState(course?.chapters?.[0]?.id ?? "");
  const [items, setItems] = useState<Item[]>([]);
  const [dragging, setDragging] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const selectId = useId();

  // Live per-document status from the indexing rollup, polled while an upload is still read.
  const indexing = useQuery({
    queryKey: ["indexing", world.id],
    queryFn: () => api.indexing(world.id),
    refetchInterval: (q) => {
      const live = liveDocs(q.state.data);
      const reading = items.some((i) => {
        if (i.state !== "uploaded" || i.reused || !i.doc) return false;
        const status = live.get(i.doc.id)?.status ?? i.doc.status;
        return status !== "ready" && status !== "failed";
      });
      return reading ? JOB_POLL_MS : false;
    },
    enabled: items.some((i) => i.state === "uploaded"),
  });
  const live = liveDocs(indexing.data);

  const chapterOf = (id: string) =>
    world.courses.flatMap((c) => c.chapters ?? []).find((ch) => ch.id === id);

  const patch = (key: string, change: Partial<Item>) =>
    setItems((xs) => xs.map((x) => (x.key === key ? { ...x, ...change } : x)));

  const add = (files: FileList | File[]) => {
    for (const file of Array.from(files)) {
      const key = `${file.name}-${file.size}-${Math.random().toString(36).slice(2)}`;
      const item: Item = {
        key,
        filename: file.name,
        size: file.size,
        chapterId,
        courseId: course?.id ?? "",
        state: "uploading",
      };
      setItems((xs) => [...xs, item]);
      if (!SUPPORTED.has(kindOf(file.name))) {
        patch(key, { state: "error", errorKey: "errors.file_type" });
        continue;
      }
      if (file.size > maxMb * 1024 * 1024) {
        patch(key, { state: "error", errorKey: "errors.file_too_large" });
        continue;
      }
      api
        .upload(chapterId, file)
        .then((up) => patch(key, { state: "uploaded", doc: up.document, reused: up.reused }))
        .catch((e: unknown) =>
          patch(key, {
            state: "error",
            errorKey: e instanceof ApiError ? e.key : "errors.unexpected",
          }),
        );
    }
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    if (e.dataTransfer.files.length) add(e.dataTransfer.files);
  };

  const filled = new Set(items.filter((i) => i.state === "uploaded").map((i) => i.courseId));
  const remaining = world.courses.filter((c) => !filled.has(c.id)).length;

  return (
    <div className="flex flex-col gap-4">
      {world.courses.length > 1 && (
        <div role="tablist" aria-label={t("summary.courses")} className="flex flex-wrap gap-2">
          {world.courses.map((c) => (
            <button
              key={c.id}
              role="tab"
              type="button"
              aria-selected={c.id === course?.id}
              onClick={() => {
                setCourseId(c.id);
                setChapterId(c.chapters?.[0]?.id ?? "");
              }}
              className={cx(
                "min-h-11 rounded-pixel-step border-2 px-3 font-semibold",
                c.id === course?.id ? "border-ink" : "border-transparent",
                accentChip(c.color_key),
              )}
            >
              <Bidi>{c.name}</Bidi>
            </button>
          ))}
        </div>
      )}

      <h2 className="text-h2">{t("upload.heading", { course: course?.name ?? "" })}</h2>

      <div className="flex flex-col gap-1">
        <label htmlFor={selectId} className="font-semibold">
          {t("upload.chapter")}
        </label>
        <select
          id={selectId}
          value={chapterId}
          onChange={(e) => setChapterId(e.target.value)}
          className="min-h-11 rounded-pixel-step border-2 border-ink bg-white px-3"
        >
          {course?.chapters?.map((ch) => (
            <option key={ch.id} value={ch.id}>
              {ch.idx} · {ch.title}
            </option>
          ))}
        </select>
      </div>

      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={cx(
          "flex flex-col items-start gap-4 rounded-soft border-2 border-dashed p-5 sm:flex-row sm:items-center",
          dragging ? "border-primary bg-primary/5" : "border-sea bg-white",
        )}
      >
        <Mascot pose="reading" scale={3} />
        <div className="flex min-w-0 flex-col gap-2">
          <p className="font-semibold">
            {t("upload.drop")}{" "}
            <button
              type="button"
              onClick={() => input.current?.click()}
              className="text-primary underline"
            >
              {t("upload.browse")}
            </button>
          </p>
          <ul className="flex flex-wrap gap-2">
            {TYPE_KEYS.map((k) => (
              <li
                key={k}
                className="rounded-pixel-step bg-sand px-2 py-0.5 text-small font-semibold"
              >
                {t(`upload.types.${k}`)}
              </li>
            ))}
          </ul>
          <p className="text-small text-ink/70">{t("upload.limit", { mb: maxMb })}</p>
        </div>
        <input
          ref={input}
          type="file"
          multiple
          accept={ACCEPT}
          className="sr-only"
          tabIndex={-1}
          aria-hidden
          onChange={(e) => {
            if (e.target.files) add(e.target.files);
            e.target.value = "";
          }}
        />
      </div>

      {items.length > 0 && (
        <ul className="flex flex-col gap-2" aria-live="polite">
          {items.map((item) => {
            const ch = chapterOf(item.chapterId);
            const doc = item.doc ? (live.get(item.doc.id) ?? item.doc) : undefined;
            return (
              <li
                key={item.key}
                className="flex items-center gap-3 rounded-soft bg-white px-3 py-2 shadow-sm"
              >
                <FileBadge filename={item.filename} />
                <div className="min-w-0 flex-1">
                  <Bidi className="block truncate font-semibold">{item.filename}</Bidi>
                  <p className="text-small text-ink/70">
                    {t("upload.meta", {
                      size: size(item.size),
                      idx: ch?.idx ?? "",
                      title: ch?.title ?? "",
                    })}
                  </p>
                  {item.state === "error" && item.errorKey && (
                    <p className="text-small text-danger">{tc(item.errorKey)}</p>
                  )}
                  {doc?.status === "failed" && doc.error && (
                    <p className="text-small text-danger">{tc(doc.error)}</p>
                  )}
                </div>
                <ItemStatus item={item} doc={doc} />
              </li>
            );
          })}
        </ul>
      )}

      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-small text-ink/70">{t("upload.remaining", { count: remaining })}</p>
        <PixelButton variant="spend" onClick={onBuild}>
          {t("nav.build")}
        </PixelButton>
      </div>
    </div>
  );
}

function ItemStatus({ item, doc }: { item: Item; doc?: DocumentOut }) {
  const { t } = useTranslation("worlds");
  if (item.state === "uploading")
    return <span className="text-small">{t("upload.status.uploading")}</span>;
  if (item.state === "error")
    return (
      <span className="text-small font-semibold text-danger">{t("upload.status.failed")}</span>
    );
  if (item.reused) return <span className="text-small">{t("upload.status.reused")}</span>;
  const status = doc?.status ?? "uploaded";
  if (status === "ready")
    return <span className="font-semibold text-olive-ink">{t("upload.status.ready")}</span>;
  if (status === "failed")
    return <span className="font-semibold text-danger">{t("upload.status.failed")}</span>;
  if (status === "uploaded")
    return <span className="text-ink/70">{t("upload.status.waiting")}</span>;
  return (
    <ProgressBar
      className="w-40 shrink-0"
      value={doc?.progress ?? 0}
      max={100}
      label={t("upload.progress", { name: item.filename, percent: doc?.progress ?? 0 })}
    />
  );
}

function liveDocs(data: IndexingOut | undefined): Map<string, DocumentOut> {
  return new Map(data?.chapters.flatMap((ch) => ch.documents.map((d) => [d.id, d] as const)) ?? []);
}
