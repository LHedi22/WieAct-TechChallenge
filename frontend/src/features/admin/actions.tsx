// Admin changes (phase C). Every form sends X-Admin-Action and a reason; destructive actions run a
// dry run first and need the target's name typed; economy changes always need a reason.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { adminCall } from "./adminApi";
import { inputClass, when } from "./format";
import { Json } from "./table";
import type {
  AnswerRow,
  ContentKind,
  ContentRow,
  JobRow,
  QuestionRow,
  UserDetail,
  WorldDetail,
} from "./types";
import { ErrorNote, Field, Pill, Section, SmallButton } from "./ui";

type Method = "POST" | "PUT" | "PATCH" | "DELETE";

function useAction<T = unknown>(after?: (data: T) => void) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      path,
      method = "POST",
      body,
    }: {
      path: string;
      method?: Method;
      body?: unknown;
    }) => adminCall<T>(path, { method, body }),
    onSuccess: (data) => {
      void qc.invalidateQueries({ queryKey: ["admin"] });
      after?.(data);
    },
  });
}

/** A collapsible form: summary line, fields, reason, submit. */
function ActionForm({
  title,
  children,
  submit,
  onSubmit,
  pending,
  error,
  done,
  tone = "primary",
  reason,
  setReason,
  reasonRequired = false,
  disabled = false,
}: {
  title: string;
  children?: ReactNode;
  submit: string;
  onSubmit: () => void;
  pending: boolean;
  error: unknown;
  done?: ReactNode;
  tone?: "primary" | "danger";
  reason: string;
  setReason: (v: string) => void;
  reasonRequired?: boolean;
  disabled?: boolean;
}) {
  const missing = reasonRequired && reason.trim().length < 3;
  return (
    <details className="rounded-soft border-2 border-sand bg-white p-3">
      <summary className="min-h-11 cursor-pointer content-center font-semibold">{title}</summary>
      <form
        className="mt-2 flex flex-col gap-3"
        onSubmit={(e: FormEvent) => {
          e.preventDefault();
          if (!missing) onSubmit();
        }}
      >
        {children}
        <Field label={reasonRequired ? "Reason (required)" : "Reason (optional)"}>
          <input
            className={inputClass}
            value={reason}
            maxLength={500}
            required={reasonRequired}
            minLength={reasonRequired ? 3 : undefined}
            onChange={(e) => setReason(e.target.value)}
          />
        </Field>
        <ErrorNote error={error} />
        {done}
        <div>
          <SmallButton type="submit" tone={tone} disabled={pending || missing || disabled}>
            {pending ? "Working…" : submit}
          </SmallButton>
        </div>
      </form>
    </details>
  );
}

function Done({ show, children }: { show: boolean; children: ReactNode }) {
  return show ? (
    <p role="status" className="text-small font-semibold text-olive-ink">
      {children}
    </p>
  ) : null;
}

// --- deletes ---------------------------------------------------------------------------------------
interface Impact {
  confirm_text: string;
  counts: Record<string, number>;
  blocked_by: { world: string }[];
  worlds_transferred?: { world: string; new_creator: string }[];
}

export function DeleteAction({
  kind,
  id,
  label,
  after,
}: {
  kind: "user" | "world" | "course" | "chapter" | "document";
  id: string;
  label: string;
  after?: () => void;
}) {
  const [impact, setImpact] = useState<Impact | null>(null);
  const [confirm, setConfirm] = useState("");
  const [reason, setReason] = useState("");
  const dry = useAction<Impact>((d) => setImpact(d));
  const del = useAction(() => after?.());
  return (
    <details className="rounded-soft border-2 border-danger/60 bg-white p-3">
      <summary className="min-h-11 cursor-pointer content-center font-semibold text-danger">
        Delete {label}…
      </summary>
      <div className="mt-2 flex flex-col gap-3 text-small">
        {!impact ? (
          <>
            <p>First see what would be deleted. Nothing is removed yet.</p>
            <div>
              <SmallButton
                onClick={() => dry.mutate({ path: `/api/admin/delete/${kind}/${id}/dry-run` })}
                disabled={dry.isPending}
              >
                {dry.isPending ? "Counting…" : "Dry run"}
              </SmallButton>
            </div>
            <ErrorNote error={dry.error} />
          </>
        ) : (
          <form
            className="flex flex-col gap-3"
            onSubmit={(e) => {
              e.preventDefault();
              del.mutate({
                path: `/api/admin/delete/${kind}/${id}`,
                method: "DELETE",
                body: { confirm, reason },
              });
            }}
          >
            <ul className="grid grid-cols-2 gap-x-4 md:grid-cols-3">
              {Object.entries(impact.counts).map(([k, v]) => (
                <li key={k}>
                  {k.replace(/_/g, " ")}: <strong>{v}</strong>
                </li>
              ))}
            </ul>
            {impact.worlds_transferred && impact.worlds_transferred.length > 0 && (
              <p>
                Worlds handed to their earliest other member:{" "}
                {impact.worlds_transferred.map((t) => t.world).join(", ")}.
              </p>
            )}
            {kind === "user" && (
              <p>
                Their coin and point ledgers are deleted with them; class-pool gifts and jobs stay,
                anonymous.
              </p>
            )}
            {impact.blocked_by.length > 0 ? (
              <p className="font-semibold text-danger">
                Blocked: delete these worlds first (no other member):{" "}
                {impact.blocked_by.map((b) => b.world).join(", ")}
              </p>
            ) : (
              <>
                <Field label={`Type "${impact.confirm_text}" to confirm`}>
                  <input
                    className={inputClass}
                    value={confirm}
                    onChange={(e) => setConfirm(e.target.value)}
                  />
                </Field>
                <Field label="Reason (required)">
                  <input
                    className={inputClass}
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                  />
                </Field>
                <ErrorNote error={del.error} />
                <Done show={del.isSuccess}>Deleted.</Done>
                <div>
                  <SmallButton
                    type="submit"
                    tone="danger"
                    disabled={
                      confirm !== impact.confirm_text || reason.trim().length < 3 || del.isPending
                    }
                  >
                    {del.isPending ? "Deleting…" : `Delete ${label}`}
                  </SmallButton>
                </div>
              </>
            )}
          </form>
        )}
      </div>
    </details>
  );
}

// --- users -----------------------------------------------------------------------------------------
export function UserActions({ u }: { u: UserDetail }) {
  const nav = useNavigate();
  return (
    <Section title="Change this student">
      <div className="grid gap-2 md:grid-cols-2">
        <EditUser u={u} />
        <CoinsForm userId={u.id} />
        <PointsForm u={u} />
        <PassForm u={u} />
        <PasswordForm userId={u.id} />
        <SignOutForm userId={u.id} />
        <ResetCourseForm u={u} />
        <DeleteAction kind="user" id={u.id} label={u.nickname} after={() => nav("/admin/users")} />
      </div>
    </Section>
  );
}

function EditUser({ u }: { u: UserDetail }) {
  const [nickname, setNickname] = useState(u.nickname);
  const [lang, setLang] = useState(u.ui_language);
  const [board, setBoard] = useState("");
  const [reason, setReason] = useState("");
  const a = useAction();
  return (
    <ActionForm
      title="Edit nickname, language, leaderboard"
      submit="Save"
      reason={reason}
      setReason={setReason}
      pending={a.isPending}
      error={a.error}
      done={<Done show={a.isSuccess}>Saved.</Done>}
      onSubmit={() =>
        a.mutate({
          path: `/api/admin/users/${u.id}`,
          method: "PATCH",
          body: {
            nickname: nickname !== u.nickname ? nickname : undefined,
            ui_language: lang !== u.ui_language ? lang : undefined,
            leaderboard_opt_in: board === "" ? undefined : board === "yes",
            reason: reason || null,
          },
        })
      }
    >
      <Field label="Nickname" hint="3–32 letters, digits, _ or -, unique">
        <input
          className={inputClass}
          value={nickname}
          onChange={(e) => setNickname(e.target.value)}
        />
      </Field>
      <Field label="UI language">
        <select className={inputClass} value={lang} onChange={(e) => setLang(e.target.value)}>
          {["en", "fr", "ar", "ar-TN"].map((l) => (
            <option key={l}>{l}</option>
          ))}
        </select>
      </Field>
      <Field label="Leaderboard">
        <select className={inputClass} value={board} onChange={(e) => setBoard(e.target.value)}>
          <option value="">unchanged</option>
          <option value="yes">shown (opt in)</option>
          <option value="no">hidden (opt out)</option>
        </select>
      </Field>
    </ActionForm>
  );
}

function CoinsForm({ userId }: { userId: string }) {
  const [bucket, setBucket] = useState("earned");
  const [delta, setDelta] = useState("5");
  const [reason, setReason] = useState("");
  const a = useAction();
  const n = Number(delta);
  return (
    <ActionForm
      title="Grant or remove coins"
      submit={n < 0 ? `Remove ${-n} coins` : `Grant ${n} coins`}
      reason={reason}
      setReason={setReason}
      reasonRequired
      disabled={!Number.isInteger(n) || n === 0}
      pending={a.isPending}
      error={a.error}
      done={<Done show={a.isSuccess}>Done: written to the ledger.</Done>}
      onSubmit={() =>
        a.mutate({ path: `/api/admin/users/${userId}/coins`, body: { bucket, delta: n, reason } })
      }
    >
      <p className="text-small text-ink/80">
        A ledger row of kind admin. The daily earn cap doesn&apos;t apply; a bucket can never go
        below zero. Free coins only count today.
      </p>
      <Field label="Bucket">
        <select className={inputClass} value={bucket} onChange={(e) => setBucket(e.target.value)}>
          <option value="free">free (today)</option>
          <option value="earned">earned</option>
          <option value="purchased">purchased</option>
        </select>
      </Field>
      <Field label="Coins (negative removes)">
        <input
          type="number"
          className={inputClass}
          value={delta}
          onChange={(e) => setDelta(e.target.value)}
        />
      </Field>
    </ActionForm>
  );
}

function PointsForm({ u }: { u: UserDetail }) {
  const [delta, setDelta] = useState("10");
  const [world, setWorld] = useState(u.worlds[0]?.id ?? "");
  const [reason, setReason] = useState("");
  const a = useAction();
  const n = Number(delta);
  return (
    <ActionForm
      title="Adjust points"
      submit={n < 0 ? `Remove ${-n} points` : `Add ${n} points`}
      reason={reason}
      setReason={setReason}
      reasonRequired
      disabled={!Number.isInteger(n) || n === 0}
      pending={a.isPending}
      error={a.error}
      done={<Done show={a.isSuccess}>Done.</Done>}
      onSubmit={() =>
        a.mutate({
          path: `/api/admin/users/${u.id}/points`,
          body: { delta: n, world_id: world || null, reason },
        })
      }
    >
      <Field label="Points (negative removes)">
        <input
          type="number"
          className={inputClass}
          value={delta}
          onChange={(e) => setDelta(e.target.value)}
        />
      </Field>
      <Field label="Counts for world (class leaderboard)">
        <select className={inputClass} value={world} onChange={(e) => setWorld(e.target.value)}>
          <option value="">none (global only)</option>
          {u.worlds.map((w) => (
            <option key={w.id} value={w.id}>
              {w.name}
            </option>
          ))}
        </select>
      </Field>
    </ActionForm>
  );
}

function PassForm({ u }: { u: UserDetail }) {
  const [reason, setReason] = useState("");
  const a = useAction();
  const action = u.wallet.pass_active ? "end" : "grant";
  return (
    <ActionForm
      title={
        u.wallet.pass_active
          ? `End the Exam Pass (until ${when(u.wallet.pass_until)})`
          : "Grant an Exam Pass"
      }
      submit={action === "end" ? "End it now" : "Grant"}
      tone={action === "end" ? "danger" : "primary"}
      reason={reason}
      setReason={setReason}
      reasonRequired
      pending={a.isPending}
      error={a.error}
      done={<Done show={a.isSuccess}>Done.</Done>}
      onSubmit={() =>
        a.mutate({ path: `/api/admin/users/${u.id}/exam-pass`, body: { action, reason } })
      }
    />
  );
}

function PasswordForm({ userId }: { userId: string }) {
  const [password, setPassword] = useState("");
  const [reason, setReason] = useState("");
  const a = useAction(() => setPassword(""));
  return (
    <ActionForm
      title="Set a new password"
      submit="Set password"
      reason={reason}
      setReason={setReason}
      pending={a.isPending}
      error={a.error}
      disabled={password.length < 8}
      done={<Done show={a.isSuccess}>Password set; the student was signed out everywhere.</Done>}
      onSubmit={() =>
        a.mutate({
          path: `/api/admin/users/${userId}/password`,
          body: { password, reason: reason || null },
        })
      }
    >
      <Field
        label="New password (at least 8 characters)"
        hint="The old one is never shown. Tell the student in person."
      >
        <input
          type="password"
          autoComplete="new-password"
          className={inputClass}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
      </Field>
    </ActionForm>
  );
}

function SignOutForm({ userId }: { userId: string }) {
  const [reason, setReason] = useState("");
  const a = useAction();
  return (
    <ActionForm
      title="Sign out everywhere"
      submit="Sign out every device"
      reason={reason}
      setReason={setReason}
      pending={a.isPending}
      error={a.error}
      done={<Done show={a.isSuccess}>Every session of this student has ended.</Done>}
      onSubmit={() =>
        a.mutate({ path: `/api/admin/users/${userId}/sign-out`, body: { reason: reason || null } })
      }
    />
  );
}

function ResetCourseForm({ u }: { u: UserDetail }) {
  const [course, setCourse] = useState(u.levels[0]?.course_id ?? "");
  const [reason, setReason] = useState("");
  const [counts, setCounts] = useState<Record<string, number> | null>(null);
  const dry = useAction<{ counts: Record<string, number> }>((d) => setCounts(d.counts));
  const run = useAction();
  if (u.levels.length === 0) return null;
  return (
    <ActionForm
      title="Reset progress in a course"
      submit={counts ? "Reset" : "Dry run"}
      tone={counts ? "danger" : "primary"}
      reason={reason}
      setReason={setReason}
      reasonRequired={Boolean(counts)}
      pending={dry.isPending || run.isPending}
      error={dry.error ?? run.error}
      done={
        <>
          {counts && !run.isSuccess && (
            <p className="text-small">
              Would delete:{" "}
              {Object.entries(counts)
                .map(([k, v]) => `${k.replace(/_/g, " ")} ${v}`)
                .join(" · ")}
            </p>
          )}
          <Done show={run.isSuccess}>Reset.</Done>
        </>
      }
      onSubmit={() => {
        const path = `/api/admin/users/${u.id}/reset-course`;
        if (!counts) dry.mutate({ path, body: { course_id: course } });
        else run.mutate({ path, body: { course_id: course, dry_run: false, reason } });
      }}
    >
      <p className="text-small text-ink/80">
        Level, chapter mastery and today&apos;s challenges. Quiz history and ledgers stay.
      </p>
      <Field label="Course">
        <select
          className={inputClass}
          value={course}
          onChange={(e) => {
            setCourse(e.target.value);
            setCounts(null);
          }}
        >
          {u.levels.map((l) => (
            <option key={l.course_id} value={l.course_id}>
              {l.course} ({l.level})
            </option>
          ))}
        </select>
      </Field>
    </ActionForm>
  );
}

// --- worlds ----------------------------------------------------------------------------------------
export function WorldActions({ w }: { w: WorldDetail }) {
  const nav = useNavigate();
  const [name, setName] = useState(w.name);
  const [reason, setReason] = useState("");
  const edit = useAction();
  const [poolDelta, setPoolDelta] = useState("10");
  const [poolReason, setPoolReason] = useState("");
  const pool = useAction();
  const [codeReason, setCodeReason] = useState("");
  const code = useAction();
  return (
    <Section title="Change this world">
      <div className="grid gap-2 md:grid-cols-2">
        <ActionForm
          title="Rename"
          submit="Save"
          reason={reason}
          setReason={setReason}
          pending={edit.isPending}
          error={edit.error}
          done={<Done show={edit.isSuccess}>Saved.</Done>}
          onSubmit={() =>
            edit.mutate({
              path: `/api/admin/worlds/${w.id}`,
              method: "PATCH",
              body: { name, reason: reason || null },
            })
          }
        >
          <Field label="Name">
            <input
              className={inputClass}
              value={name}
              maxLength={80}
              onChange={(e) => setName(e.target.value)}
            />
          </Field>
        </ActionForm>
        <ActionForm
          title={`New join code (now ${w.join_code})`}
          submit="Regenerate"
          reason={codeReason}
          setReason={setCodeReason}
          pending={code.isPending}
          error={code.error}
          done={<Done show={code.isSuccess}>New code made; the old one no longer works.</Done>}
          onSubmit={() =>
            code.mutate({
              path: `/api/admin/worlds/${w.id}`,
              method: "PATCH",
              body: { regenerate_join_code: true, reason: codeReason || null },
            })
          }
        />
        <ActionForm
          title={`Credit or debit the class pool (${w.pool.balance})`}
          submit="Apply"
          reason={poolReason}
          setReason={setPoolReason}
          reasonRequired
          disabled={!Number.isInteger(Number(poolDelta)) || Number(poolDelta) === 0}
          pending={pool.isPending}
          error={pool.error}
          done={<Done show={pool.isSuccess}>Done.</Done>}
          onSubmit={() =>
            pool.mutate({
              path: `/api/admin/worlds/${w.id}/pool`,
              body: { delta: Number(poolDelta), reason: poolReason },
            })
          }
        >
          <Field label="Coins (negative debits; never below zero)">
            <input
              type="number"
              className={inputClass}
              value={poolDelta}
              onChange={(e) => setPoolDelta(e.target.value)}
            />
          </Field>
        </ActionForm>
        <DeleteAction kind="world" id={w.id} label={w.name} after={() => nav("/admin/worlds")} />
      </div>
    </Section>
  );
}

export function MemberRemove({
  worldId,
  userId,
  nickname,
}: {
  worldId: string;
  userId: string;
  nickname: string;
}) {
  return (
    <RowAction
      label="Remove"
      tone="danger"
      method="DELETE"
      ask={`Reason to remove ${nickname} from this world`}
      path={`/api/admin/worlds/${worldId}/members/${userId}`}
      body={{}}
    />
  );
}

export function CourseActions({ c }: { c: WorldDetail["courses"][number] }) {
  const [name, setName] = useState(c.name);
  const [exam, setExam] = useState(c.exam_date ?? "");
  const [reason, setReason] = useState("");
  const a = useAction();
  return (
    <div className="mb-3 grid gap-2 md:grid-cols-2">
      <ActionForm
        title="Edit course"
        submit="Save"
        reason={reason}
        setReason={setReason}
        pending={a.isPending}
        error={a.error}
        done={<Done show={a.isSuccess}>Saved.</Done>}
        onSubmit={() =>
          a.mutate({
            path: `/api/admin/courses/${c.id}`,
            method: "PATCH",
            body: {
              name,
              exam_date: exam || undefined,
              clear_exam_date: !exam,
              reason: reason || null,
            },
          })
        }
      >
        <Field label="Name">
          <input className={inputClass} value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label="Exam date (empty = none)">
          <input
            type="date"
            className={inputClass}
            value={exam}
            onChange={(e) => setExam(e.target.value)}
          />
        </Field>
      </ActionForm>
      <DeleteAction kind="course" id={c.id} label={c.name} />
    </div>
  );
}

export function ChapterActions({ ch }: { ch: { id: string; title: string } }) {
  const [title, setTitle] = useState(ch.title);
  const [reason, setReason] = useState("");
  const edit = useAction();
  const re = useAction<{ jobs: string[] }>();
  return (
    <div className="my-2 grid gap-2 md:grid-cols-3">
      <ActionForm
        title="Rename chapter"
        submit="Save"
        reason={reason}
        setReason={setReason}
        pending={edit.isPending}
        error={edit.error}
        done={<Done show={edit.isSuccess}>Saved.</Done>}
        onSubmit={() =>
          edit.mutate({
            path: `/api/admin/chapters/${ch.id}`,
            method: "PATCH",
            body: { title, reason: reason || null },
          })
        }
      >
        <Field label="Title">
          <input className={inputClass} value={title} onChange={(e) => setTitle(e.target.value)} />
        </Field>
      </ActionForm>
      <div className="flex flex-col gap-1 rounded-soft border-2 border-sand bg-white p-3 text-small">
        <SmallButton
          disabled={re.isPending}
          onClick={() => re.mutate({ path: `/api/admin/chapters/${ch.id}/reindex`, body: {} })}
        >
          Re-index chapter
        </SmallButton>
        {re.isSuccess && (
          <span>
            {re.data.jobs.length} indexing job(s) queued (background lane; waits for the slot).
          </span>
        )}
        <ErrorNote error={re.error} />
      </div>
      <DeleteAction kind="chapter" id={ch.id} label={ch.title} />
    </div>
  );
}

export function DocumentActions({ id, filename }: { id: string; filename: string }) {
  const re = useAction();
  return (
    <div className="flex flex-wrap items-start gap-2">
      <SmallButton
        disabled={re.isPending}
        onClick={() => re.mutate({ path: `/api/admin/documents/${id}/reindex`, body: {} })}
      >
        {re.isSuccess ? "Queued" : "Re-index"}
      </SmallButton>
      <DeleteAction kind="document" id={id} label={filename} />
      <ErrorNote error={re.error} />
    </div>
  );
}

// --- content ---------------------------------------------------------------------------------------
export function ContentEditor({ kind, c }: { kind: ContentKind; c: ContentRow }) {
  const [text, setText] = useState(JSON.stringify(c.body, null, 2));
  const [reason, setReason] = useState("");
  const [parseError, setParseError] = useState<string | null>(null);
  const a = useAction();
  return (
    <>
      <Json value={c.body} />
      <ActionForm
        title="Edit this content"
        submit="Validate and save"
        reason={reason}
        setReason={setReason}
        reasonRequired
        pending={a.isPending}
        error={parseError ?? a.error}
        done={<Done show={a.isSuccess}>Saved. It is now marked “edited by admin”.</Done>}
        onSubmit={() => {
          let body: unknown;
          try {
            body = JSON.parse(text);
          } catch {
            setParseError("That isn't valid JSON.");
            return;
          }
          setParseError(null);
          a.mutate({
            path: `/api/admin/content/${kind}/${c.id}`,
            method: "PUT",
            body: { body, reason },
          });
        }}
      >
        <p className="text-small text-ink/80">
          Checked with the same schemas the app uses. Edited content is labelled and must never be
          reported as pure AI output.
        </p>
        <Field label="JSON">
          <textarea
            className={`${inputClass} min-h-64 font-mono text-small`}
            value={text}
            spellCheck={false}
            onChange={(e) => setText(e.target.value)}
          />
        </Field>
      </ActionForm>
    </>
  );
}

// --- arena -----------------------------------------------------------------------------------------
/** A row button that opens an inline confirm with a reason (and an optional score). */
function RowAction({
  label,
  path,
  body,
  tone = "default",
  ask,
  score = false,
  method = "POST",
}: {
  label: string;
  path: string;
  body: Record<string, unknown>;
  tone?: "default" | "danger" | "primary";
  ask?: string;
  score?: boolean;
  method?: Method;
}) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [value, setValue] = useState("");
  const a = useAction(() => setOpen(false));
  const n = Number(value);
  const ready =
    reason.trim().length >= 3 &&
    (!score || (value !== "" && Number.isInteger(n) && n >= 0 && n <= 100));
  if (!open)
    return (
      <span className="inline-flex flex-col gap-1">
        <SmallButton tone={tone} onClick={() => setOpen(true)}>
          {label}
        </SmallButton>
        {a.isSuccess && <span className="text-small text-olive-ink">Done</span>}
      </span>
    );
  return (
    <form
      className="flex w-full min-w-56 flex-col gap-2 rounded-soft border-2 border-sand bg-whitewash p-2"
      onSubmit={(e) => {
        e.preventDefault();
        if (ready)
          a.mutate({ path, method, body: { ...body, ...(score ? { score: n } : {}), reason } });
      }}
    >
      {score && (
        <Field label="Score 0–100" hint="Rewards are paid once if it reaches the threshold.">
          <input
            type="number"
            min={0}
            max={100}
            className={inputClass}
            value={value}
            onChange={(e) => setValue(e.target.value)}
          />
        </Field>
      )}
      <Field label={ask ?? `Reason to ${label.toLowerCase()}`}>
        <input className={inputClass} value={reason} onChange={(e) => setReason(e.target.value)} />
      </Field>
      <ErrorNote error={a.error} />
      <div className="flex gap-2">
        <SmallButton
          type="submit"
          tone={tone === "default" ? "primary" : tone}
          disabled={!ready || a.isPending}
        >
          {label}
        </SmallButton>
        <SmallButton onClick={() => setOpen(false)}>Cancel</SmallButton>
      </div>
    </form>
  );
}

export function AnswerActions({ a }: { a: AnswerRow }) {
  const path = `/api/admin/arena/answers/${a.id}`;
  return (
    <div className="flex flex-wrap gap-1">
      {a.status === "pending_review" && <ScoreAnswer id={a.id} />}
      {a.status !== "rejected" ? (
        <RowAction label="Reject" tone="danger" path={path} body={{ action: "reject" }} />
      ) : (
        <RowAction label="Restore" path={path} body={{ action: "restore" }} />
      )}
    </div>
  );
}

function ScoreAnswer({ id }: { id: string }) {
  return (
    <RowAction
      label="Set score"
      tone="primary"
      score
      path={`/api/admin/arena/answers/${id}`}
      body={{ action: "score" }}
    />
  );
}

export function QuestionActions({ q }: { q: QuestionRow }) {
  const path = `/api/admin/arena/questions/${q.id}`;
  return (
    <div className="flex flex-wrap gap-1">
      {q.status !== "rejected" ? (
        <RowAction label="Reject" tone="danger" path={path} body={{ action: "reject" }} />
      ) : (
        <RowAction label="Restore" path={path} body={{ action: "restore" }} />
      )}
      {q.pinned_answer_id && <RowAction label="Unpin" path={path} body={{ action: "unpin" }} />}
    </div>
  );
}

// --- jobs and cache --------------------------------------------------------------------------------
export function JobActions({ j }: { j: JobRow }) {
  const base = `/api/admin/jobs/${j.id}`;
  return (
    <div className="flex flex-wrap gap-1">
      {(j.status === "queued" || j.status === "running") && (
        <RowAction
          label="Cancel"
          tone="danger"
          path={`${base}/cancel`}
          body={{}}
          ask="Reason to cancel (coins are refunded once)?"
        />
      )}
      {j.status === "queued" && j.not_before && (
        <RowAction label="Run now" path={`${base}/run-now`} body={{}} />
      )}
      {(j.status === "failed" || j.status === "cancelled") && (
        <RowAction
          label="Retry"
          path={`${base}/retry`}
          body={{}}
          ask="Reason to retry (free for the student)?"
        />
      )}
    </div>
  );
}

interface PurgeOut {
  dry_run: boolean;
  entries: number;
  cloud_entries: number;
  warning: string | null;
  confirm_text?: string | null;
}

export function CachePurge() {
  const [taskKind, setTaskKind] = useState("");
  const [key, setKey] = useState("");
  const [provider, setProvider] = useState("");
  const [reason, setReason] = useState("");
  const [preview, setPreview] = useState<PurgeOut | null>(null);
  const [typed, setTyped] = useState("");
  const dry = useAction<PurgeOut>((d) => setPreview(d));
  const run = useAction<PurgeOut>(() => setPreview(null));
  const body = { task_kind: taskKind || null, key: key || null, provider: provider || null };
  return (
    <ActionForm
      title="Purge cache entries"
      submit={preview ? `Purge ${preview.entries} entries` : "Dry run"}
      tone={preview ? "danger" : "primary"}
      reason={reason}
      setReason={setReason}
      reasonRequired={Boolean(preview)}
      disabled={
        (!taskKind && !key) || Boolean(preview?.confirm_text && typed !== preview.confirm_text)
      }
      pending={dry.isPending || run.isPending}
      error={dry.error ?? run.error}
      done={
        <>
          {preview?.warning && (
            <p
              role="alert"
              className="rounded-soft border-2 border-terracotta-ink bg-terracotta-light/25 p-2 text-small font-semibold text-terracotta-ink"
            >
              {preview.warning}
            </p>
          )}
          {preview?.confirm_text && (
            <Field label={`Type "${preview.confirm_text}" to purge platform entries`}>
              <input
                className={inputClass}
                value={typed}
                onChange={(e) => setTyped(e.target.value)}
              />
            </Field>
          )}
          <Done show={run.isSuccess}>Purged {run.data?.entries} entries.</Done>
        </>
      }
      onSubmit={() => {
        if (!preview)
          dry.mutate({ path: "/api/admin/cache/purge", body: { ...body, dry_run: true } });
        else
          run.mutate({
            path: "/api/admin/cache/purge",
            body: { ...body, dry_run: false, reason, confirm: typed || null },
          });
      }}
    >
      <p className="text-small text-ink/80">
        By key or task kind. Keys are hashes of the whole request, so there is no purge by chapter
        (edit that chapter&apos;s content instead).
      </p>
      <Field label="Task kind">
        <input
          className={inputClass}
          value={taskKind}
          onChange={(e) => {
            setTaskKind(e.target.value);
            setPreview(null);
          }}
          placeholder="e.g. NOTES_WRITE"
        />
      </Field>
      <Field label="Exact key">
        <input
          className={inputClass}
          value={key}
          onChange={(e) => {
            setKey(e.target.value);
            setPreview(null);
          }}
        />
      </Field>
      <Field label="Provider">
        <select
          className={inputClass}
          value={provider}
          onChange={(e) => {
            setProvider(e.target.value);
            setPreview(null);
          }}
        >
          <option value="">any</option>
          <option>cloud</option>
          <option>local</option>
          <option>mock</option>
        </select>
      </Field>
    </ActionForm>
  );
}

// --- economy ---------------------------------------------------------------------------------------
interface OverrideRow {
  key: string;
  default: number;
  effective: number;
  overridden: boolean;
  min: number;
  max: number;
  updated_at: string | null;
  updated_by: string | null;
}

interface Violation {
  check: string;
  [k: string]: unknown;
}

export function EconomyPage() {
  const q = useQuery({
    queryKey: ["admin", "economy"],
    queryFn: () => adminCall<{ items: OverrideRow[] }>("/api/admin/economy"),
  });
  const inv = useMutation({
    mutationFn: () =>
      adminCall<{ ok: boolean; violations: Violation[]; checked_at: string }>(
        "/api/admin/invariants",
      ),
  });
  return (
    <div className="flex max-w-4xl flex-col gap-4">
      <h1 className="font-heading text-h2">Economy</h1>
      <p className="text-small text-ink/80">
        Live values merged over economy.py, used by /api/economy, every price and the wallet within
        ~3 s. Coins already reserved by running jobs don&apos;t change. Every change needs a reason.
      </p>
      <Section
        title="Invariant check"
        actions={
          <SmallButton onClick={() => inv.mutate()} disabled={inv.isPending}>
            {inv.isPending ? "Checking…" : "Run the check"}
          </SmallButton>
        }
      >
        <p className="text-small text-ink/80">
          No negative bucket or pool, no duplicate reward, no double refund, no failed paid job left
          unrefunded. It reports and fixes nothing.
        </p>
        <ErrorNote error={inv.error} />
        {inv.data &&
          (inv.data.ok ? (
            <p role="status" className="mt-2 font-semibold text-olive-ink">
              All good ({when(inv.data.checked_at)}).
            </p>
          ) : (
            <div className="mt-2">
              <Pill tone="warn">{inv.data.violations.length} violations</Pill>
              <Json value={inv.data.violations} />
            </div>
          ))}
      </Section>
      {q.error && <ErrorNote error={q.error} />}
      {q.data && (
        <Section title="Numbers">
          <ul className="flex flex-col divide-y divide-sand">
            {q.data.items.map((row) => (
              <OverrideItem key={row.key} row={row} />
            ))}
          </ul>
        </Section>
      )}
    </div>
  );
}

function OverrideItem({ row }: { row: OverrideRow }) {
  const [value, setValue] = useState(String(row.effective));
  const [reason, setReason] = useState("");
  const a = useAction();
  const n = Number(value);
  const valid = Number.isInteger(n) && n >= row.min && n <= row.max;
  return (
    <li className="flex flex-wrap items-end gap-2 py-2 text-small">
      <div className="min-w-48 flex-1">
        <code className="font-semibold">{row.key}</code>
        <div className="text-ink/70">
          default {row.default}
          {row.overridden && (
            <>
              {" "}
              · <Pill tone="warn">now {row.effective}</Pill> by {row.updated_by ?? "?"}{" "}
              {when(row.updated_at)}
            </>
          )}
        </div>
      </div>
      <label className="flex flex-col">
        <span className="sr-only">{row.key} value</span>
        <input
          type="number"
          min={row.min}
          max={row.max}
          className={`${inputClass} w-24`}
          value={value}
          onChange={(e) => setValue(e.target.value)}
        />
      </label>
      <label className="flex flex-col">
        <span className="sr-only">{row.key} reason</span>
        <input
          className={`${inputClass} w-48`}
          placeholder="reason"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
        />
      </label>
      <SmallButton
        tone="primary"
        disabled={!valid || n === row.effective || reason.trim().length < 3 || a.isPending}
        onClick={() =>
          a.mutate({
            path: `/api/admin/economy/${row.key}`,
            method: "PUT",
            body: { value: n, reason },
          })
        }
      >
        Set
      </SmallButton>
      {row.overridden && (
        <SmallButton
          disabled={reason.trim().length < 3 || a.isPending}
          onClick={() =>
            a.mutate({
              path: `/api/admin/economy/${row.key}`,
              method: "PUT",
              body: { value: null, reason },
            })
          }
        >
          Default
        </SmallButton>
      )}
      {a.error && <span className="w-full text-danger">{(a.error as Error).message}</span>}
    </li>
  );
}
