import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";
import { api, type DocumentOut, type IndexingChapter, type IndexingOut } from "@/api/client";
import {
  Bidi,
  LanguageSwitcher,
  Mascot,
  PixelButton,
  PixelPanel,
  ProgressBar,
  Sprite,
  WaterTile,
} from "@/components";
import { cx } from "@/components/cx";
import { JOB_POLL_MS } from "@/hooks/useJob";
import { ErrorBanner } from "./parts";

type RowState = IndexingChapter["state"];

/** /worlds/:id/indexing — mockup 05: "Raising your islands" + invite your class. */
export function IndexingPage() {
  const { worldId = "" } = useParams();
  const { t } = useTranslation("worlds");
  const query = useQuery({
    queryKey: ["indexing", worldId],
    queryFn: () => api.indexing(worldId),
    // Poll until everything (files + quiz pools) is done; no streaming on the platform.
    refetchInterval: (q) => (isFinished(q.state.data) ? false : JOB_POLL_MS),
  });
  const data = query.data;

  return (
    <main className="mx-auto flex max-w-screen-xl flex-col gap-6 px-4 py-6 sm:px-8">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <span className="flex items-center gap-2 font-heading text-h3">
          <Sprite name="oliveBranch" scale={2} />
          {t("common:app.name")}
        </span>
        <div className="flex items-center gap-4">
          {data && (
            <span>
              <span className="text-ink/70">{t("worldLabel")} </span>
              <Bidi className="font-semibold">{data.name}</Bidi>
            </span>
          )}
          <LanguageSwitcher />
        </div>
      </header>
      <ErrorBanner error={query.error} />

      {data && (
        <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,22rem)]">
          <section className="flex min-w-0 flex-col gap-5">
            <Scene data={data} />
            <div className="flex flex-wrap items-end justify-between gap-2">
              <h1 className="text-h1">{data.done ? t("indexing.done") : t("indexing.title")}</h1>
              <p className="text-ink/70">{etaText(t, data)}</p>
            </div>
            <ProgressBar value={data.percent} max={100} label={t("indexing.progress")} />
            <ol className="flex flex-col gap-2">
              {data.chapters.map((ch) => (
                <Row
                  key={ch.chapter_id}
                  state={ch.state}
                  title={t("indexing.row", { idx: ch.idx, title: ch.title })}
                  detail={rowDetail(t, ch)}
                />
              ))}
              <Row
                state={data.quizzes.state === "done" ? "done" : data.quizzes.state}
                title={t("indexing.quizzes")}
                label={t(`indexing.quizzesState.${data.quizzes.state}`)}
              />
            </ol>
          </section>

          <aside className="flex min-w-0 flex-col gap-5">
            <InviteCard code={data.join_code} />
            <p className="flex items-start gap-3 text-small">
              <Sprite name="lantern" scale={2} />
              <span>{t("indexing.tip")}</span>
            </p>
            <Link
              to={`/worlds/${worldId}`}
              className="inline-flex min-h-11 items-center self-start rounded-pixel-step bg-primary px-4 font-semibold text-white shadow-lip"
            >
              {t("indexing.goToWorld")}
            </Link>
          </aside>
        </div>
      )}
    </main>
  );
}

function isFinished(data: IndexingOut | undefined): boolean {
  return !!data && data.done && data.quizzes.state !== "in_progress";
}

type T = ReturnType<typeof useTranslation>["t"];

function etaText(t: T, data: IndexingOut): string {
  if (data.done) return "";
  const minutes = Math.ceil(data.eta_s / 60);
  return data.eta_s < 45 ? t("indexing.etaSoon") : t("indexing.eta", { minutes });
}

function rowDetail(t: T, ch: IndexingChapter): string {
  const pages = ch.documents.reduce((n, d) => n + (d.page_count ?? 0), 0);
  const parts = [t("indexing.files", { count: ch.documents.length })];
  if (pages) parts.push(t("indexing.pages", { count: pages }));
  return parts.join(" · ");
}

/** What is being read right now: "Ch2_slides.pptx · slide 18 of 42". */
function current(data: IndexingOut): { chapter: IndexingChapter; doc: DocumentOut } | null {
  for (const chapter of data.chapters) {
    const doc = chapter.documents.find((d) =>
      ["parsing", "tagging", "embedding"].includes(d.status),
    );
    if (doc) return { chapter, doc };
  }
  return null;
}

function Scene({ data }: { data: IndexingOut }) {
  const { t } = useTranslation("worlds");
  const now = current(data);
  const detail = now?.doc.detail as { key?: string; n?: number; of?: number } | null | undefined;
  return (
    <WaterTile className="flex min-h-56 items-center justify-center rounded-pixel-step border-2 border-ink p-6">
      <div className="flex max-w-md items-center gap-4 rounded-pixel-step border-2 border-ink bg-white p-4 shadow-panel">
        <Mascot pose={data.done ? "celebrating" : "reading"} scale={3} />
        <div className="min-w-0" aria-live="polite">
          <p className="font-heading text-h3">
            {data.done
              ? t("indexing.done")
              : now
                ? t("indexing.now", { title: now.chapter.title })
                : t("indexing.title")}
          </p>
          {now && detail?.key && (
            <p className="text-small text-ink/70">
              <Bidi>
                {t(`indexing.detail.${detail.key}`, {
                  file: now.doc.filename,
                  n: detail.n ?? 0,
                  of: detail.of ?? 0,
                })}
              </Bidi>
            </p>
          )}
        </div>
      </div>
    </WaterTile>
  );
}

const ROW_STYLE: Record<RowState, string> = {
  done: "bg-white",
  in_progress: "border-2 border-primary bg-primary/5",
  waiting: "bg-white",
  failed: "bg-white",
};

function Row({
  state,
  title,
  detail,
  label,
}: {
  state: RowState;
  title: string;
  detail?: string;
  label?: string;
}) {
  const { t } = useTranslation("worlds");
  return (
    <li className={cx("flex items-center gap-3 rounded-soft px-4 py-3", ROW_STYLE[state])}>
      <span
        aria-hidden
        className={cx(
          "inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-pixel-step text-small text-white",
          state === "done" ? "bg-olive-ink" : state === "failed" ? "bg-danger" : "bg-sand",
        )}
      >
        {state === "done" ? "✓" : state === "in_progress" ? "···" : ""}
      </span>
      <span className="min-w-0 flex-1">
        <Bidi className="font-semibold">{title}</Bidi>
        {detail && <span className="text-ink/70"> · {detail}</span>}
      </span>
      <span
        className={cx(
          "shrink-0 text-small font-semibold",
          state === "done" && "text-olive-ink",
          state === "in_progress" && "text-primary",
          state === "failed" && "text-danger",
          state === "waiting" && "text-ink/70",
        )}
      >
        {label ?? t(`indexing.state.${state}`)}
      </span>
    </li>
  );
}

function InviteCard({ code }: { code: string }) {
  const { t } = useTranslation("worlds");
  const [copied, setCopied] = useState(false);
  const link = `${window.location.origin}/join/${code}`;
  const copy = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      /* clipboard blocked: the code stays visible to copy by hand */
    }
  };
  const share = async () => {
    const text = t("invite.shareText", { code });
    if (navigator.share) {
      try {
        await navigator.share({ title: t("invite.title"), text, url: link });
        return;
      } catch {
        /* dismissed or unsupported: fall back to copying the link */
      }
    }
    await copy(`${text} ${link}`);
  };
  return (
    <PixelPanel className="flex flex-col gap-4">
      <div className="flex items-start justify-between gap-3">
        <h2 className="text-h2">{t("invite.title")}</h2>
        <Sprite name="blueDoor" scale={3} />
      </div>
      <p className="text-ink/80">{t("invite.body")}</p>
      <div className="rounded-pixel-step border-2 border-sand-dark bg-sand/40 p-4 text-center">
        <p className="text-small font-semibold text-ink/70">{t("invite.code")}</p>
        <p dir="ltr" className="font-heading text-h1 tracking-[0.2em]" data-testid="join-code">
          {code}
        </p>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <PixelButton variant="secondary" onClick={() => void copy(code)}>
          {copied ? t("invite.copied") : t("invite.copy")}
        </PixelButton>
        <PixelButton variant="spend" onClick={() => void share()}>
          {t("invite.share")}
        </PixelButton>
      </div>
      <p className="text-small text-ink/70">{t("invite.hint")}</p>
    </PixelPanel>
  );
}
