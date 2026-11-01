import { useTranslation } from "react-i18next";
import type { MindMap, StudyNotes } from "@/api/client";
import { Bidi, MathText, SoftCard } from "@/components";

/** Revision notes: sections with points and their page/slide refs, then the key terms. */
export function NotesView({ notes }: { notes: StudyNotes }) {
  const { t } = useTranslation("studio");
  return (
    <article className="flex flex-col gap-4" data-testid="notes" dir="auto">
      {notes.title && <h2 className="text-h2">{notes.title}</h2>}
      {notes.sections.map((s, i) => (
        <SoftCard key={i} className="flex flex-col gap-2">
          <h3 className="text-h3">
            <MathText text={s.heading} />
          </h3>
          <ul className="flex list-disc flex-col gap-1 ps-5">
            {s.points.map((p, j) => (
              <li key={j}>
                <MathText text={p} />
              </li>
            ))}
          </ul>
          {s.refs.length > 0 && (
            <p className="flex flex-wrap items-center gap-2 text-small text-ink/70">
              {t("source")}
              {s.refs.map((r) => (
                <span key={r} className="rounded-soft bg-sand/40 px-2 py-0.5">
                  <Ref value={r} />
                </span>
              ))}
            </p>
          )}
        </SoftCard>
      ))}
      {notes.key_terms.length > 0 && (
        <SoftCard className="flex flex-col gap-2 bg-sand/20">
          <h3 className="text-h3">{t("keyTerms")}</h3>
          <dl className="grid gap-x-4 gap-y-2 sm:grid-cols-[auto_1fr]">
            {notes.key_terms.map((k) => (
              <div key={k.term} className="contents">
                <dt className="font-semibold">
                  <MathText text={k.term} />
                </dt>
                <dd>
                  <MathText text={k.meaning} />
                </dd>
              </div>
            ))}
          </dl>
        </SoftCard>
      )}
    </article>
  );
}

/** "page:12" → "Page 12" in the reader's language. */
function Ref({ value }: { value: string }) {
  const { t } = useTranslation("studio");
  const [kind, n] = value.split(":");
  return (
    <>
      {t(`ref.${kind}`, { defaultValue: kind })} <Bidi>{n}</Bidi>
    </>
  );
}

/** The mind map as a tree of nested lists: the central topic, its branches and their details.
 * Built with logical borders, so it mirrors in Arabic, and it is its own accessible list view. */
export function MindMapView({ map }: { map: MindMap }) {
  const { t } = useTranslation("studio");
  return (
    <figure className="flex flex-col items-center gap-0" data-testid="mind-map">
      <figcaption className="sr-only">{t("tabs.map")}</figcaption>
      <p
        className="max-w-md rounded-pixel-step border-2 border-ink bg-primary px-4 py-3 text-center font-heading text-h3 text-white shadow-panel"
        dir="auto"
      >
        <MathText text={map.root} />
      </p>
      <span aria-hidden className="h-6 w-0.5 bg-ink" />
      <ul
        aria-label={map.root}
        className="grid w-full gap-4 border-t-2 border-ink pt-6 sm:grid-cols-2 lg:grid-cols-3"
      >
        {map.branches.map((b, i) => (
          <li key={i}>
            <SoftCard className="flex h-full flex-col gap-2 border-s-8 border-s-olive">
              <p className="font-heading text-h3" dir="auto">
                <MathText text={b.label} />
              </p>
              {b.children.length > 0 && (
                <ul className="flex flex-col gap-1 border-s-2 border-sand ps-3">
                  {b.children.map((c, j) => (
                    <li key={j} dir="auto">
                      <MathText text={c} />
                    </li>
                  ))}
                </ul>
              )}
            </SoftCard>
          </li>
        ))}
      </ul>
    </figure>
  );
}
