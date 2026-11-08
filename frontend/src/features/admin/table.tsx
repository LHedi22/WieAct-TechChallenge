// Dense list pages: filter bar, table (cards on phones), pager. Server-side paging, 50 per page.
import { useState, type ReactNode } from "react";
import { usePaged, type Filters } from "./hooks";
import { inputClass } from "./format";
import { ErrorNote, SmallButton } from "./ui";

export interface Column<T> {
  label: string;
  render: (row: T) => ReactNode;
  className?: string;
}

export interface FilterSpec {
  key: string;
  label: string;
  options?: string[]; // a select; otherwise a text box
  placeholder?: string;
}

export function FilterBar({
  specs,
  value,
  onChange,
}: {
  specs: FilterSpec[];
  value: Filters;
  onChange: (next: Filters) => void;
}) {
  const [draft, setDraft] = useState(value);
  return (
    <form
      className="flex flex-wrap items-end gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        onChange(draft);
      }}
    >
      {specs.map((f) => (
        <label key={f.key} className="flex min-w-36 flex-1 flex-col gap-1 text-small md:flex-none">
          <span className="font-semibold">{f.label}</span>
          {f.options ? (
            <select
              className={inputClass}
              value={draft[f.key] ?? ""}
              onChange={(e) => {
                const next = { ...draft, [f.key]: e.target.value };
                setDraft(next);
                onChange(next);
              }}
            >
              <option value="">all</option>
              {f.options.map((o) => (
                <option key={o} value={o}>
                  {o}
                </option>
              ))}
            </select>
          ) : (
            <input
              className={inputClass}
              value={draft[f.key] ?? ""}
              placeholder={f.placeholder}
              onChange={(e) => setDraft({ ...draft, [f.key]: e.target.value })}
            />
          )}
        </label>
      ))}
      <SmallButton type="submit">Search</SmallButton>
    </form>
  );
}

export function DataTable<T>({
  columns,
  rows,
  rowKey,
  onOpen,
  empty = "Nothing found.",
}: {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  onOpen?: (row: T) => void;
  empty?: string;
}) {
  if (rows.length === 0) return <p className="py-4 text-small text-ink/70">{empty}</p>;
  return (
    <>
      {/* phones: one card per row */}
      <ul className="flex flex-col gap-2 md:hidden">
        {rows.map((r) => (
          <li key={rowKey(r)} className="rounded-soft border-2 border-sand bg-white p-3 text-small">
            <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
              {columns.map((c) => {
                const v = c.render(r);
                if (v === "—" || v === null || v === undefined || v === "") return null;
                return (
                  <div key={c.label} className="contents">
                    <dt className="text-ink/80">{c.label}</dt>
                    <dd className="min-w-0 break-words">{v}</dd>
                  </div>
                );
              })}
            </dl>
            {onOpen && (
              <div className="mt-2">
                <SmallButton onClick={() => onOpen(r)}>Open</SmallButton>
              </div>
            )}
          </li>
        ))}
      </ul>
      <div className="hidden overflow-x-auto md:block">
        <table className="w-full text-small">
          <thead>
            <tr className="border-b-2 border-sand">
              {columns.map((c) => (
                <th
                  key={c.label}
                  scope="col"
                  className="whitespace-nowrap px-2 py-1.5 text-start font-semibold"
                >
                  {c.label}
                </th>
              ))}
              {onOpen && <th scope="col" className="px-2" aria-label="Open" />}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={rowKey(r)} className="border-b border-sand/60 align-top hover:bg-whitewash">
                {columns.map((c) => (
                  <td key={c.label} className={c.className ?? "px-2 py-1.5"}>
                    {c.render(r)}
                  </td>
                ))}
                {onOpen && (
                  <td className="px-2 py-1">
                    <SmallButton onClick={() => onOpen(r)}>Open</SmallButton>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

export function Pager({
  page,
  total,
  pageSize,
  onPage,
}: {
  page: number;
  total: number;
  pageSize: number;
  onPage: (p: number) => void;
}) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  return (
    <nav aria-label="Pages" className="flex flex-wrap items-center gap-2 text-small">
      <SmallButton disabled={page <= 1} onClick={() => onPage(page - 1)}>
        Previous
      </SmallButton>
      <span>
        Page {page} of {pages} · {total} total
      </span>
      <SmallButton disabled={page >= pages} onClick={() => onPage(page + 1)}>
        Next
      </SmallButton>
    </nav>
  );
}

/** A filterable, paged list. */
export function ListView<T>({
  title,
  path,
  specs,
  columns,
  rowKey,
  onOpen,
  intro,
  initial = {},
}: {
  title: string;
  path: string;
  specs: FilterSpec[];
  columns: Column<T>[];
  rowKey: (row: T) => string;
  onOpen?: (row: T) => void;
  intro?: ReactNode;
  initial?: Filters;
}) {
  const [filters, setFilters] = useState<Filters>(initial);
  const [page, setPage] = useState(1);
  const q = usePaged<T>(path, filters, page);
  return (
    <div className="flex flex-col gap-4">
      <h1 className="font-heading text-h2">{title}</h1>
      {intro}
      <FilterBar
        specs={specs}
        value={filters}
        onChange={(f) => {
          setFilters(f);
          setPage(1);
        }}
      />
      {q.error ? (
        <ErrorNote error={q.error} />
      ) : !q.data ? (
        <p className="text-small">Loading…</p>
      ) : (
        <>
          <DataTable columns={columns} rows={q.data.items} rowKey={rowKey} onOpen={onOpen} />
          <Pager page={page} total={q.data.total} pageSize={q.data.page_size} onPage={setPage} />
        </>
      )}
    </div>
  );
}

export function Json({ value }: { value: unknown }) {
  return (
    <pre className="max-h-[60vh] overflow-auto whitespace-pre-wrap break-words rounded-soft border-2 border-sand bg-whitewash p-3 text-small">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}
