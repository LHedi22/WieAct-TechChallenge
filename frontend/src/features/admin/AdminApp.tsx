// /admin: a separate, lazy-loaded chunk. English only and always left-to-right, whatever the
// student UI language is. Never shows the platform URL, keys, .env values or the admin token.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Navigate, NavLink, Route, Routes } from "react-router-dom";
import { cx } from "@/components/cx";
import { AdminError, adminApi, type AdminMe } from "./adminApi";
import { HOME, NAV } from "./nav";
import { inputClass } from "./format";
import { ErrorNote, Field, SmallButton } from "./ui";

export default function AdminApp() {
  const me = useQuery({ queryKey: ["admin", "me"], queryFn: adminApi.me, retry: false });
  let body;
  if (me.isPending) body = <p className="p-6 text-small">Loading…</p>;
  else if (me.error instanceof AdminError && me.error.status === 404)
    body = (
      <Centered title="Admin is off">
        <p>This server has no ADMIN_TOKEN, so the admin side doesn&apos;t exist here.</p>
      </Centered>
    );
  else if (me.error) body = <SignIn />;
  else body = <Shell me={me.data} />;
  return (
    <div dir="ltr" lang="en" className="min-h-screen bg-whitewash font-body text-body text-ink">
      {body}
    </div>
  );
}

function Centered({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <main className="mx-auto flex max-w-md flex-col gap-4 px-4 py-12">
      <h1 className="font-heading text-h2">{title}</h1>
      {children}
    </main>
  );
}

function SignIn() {
  const qc = useQueryClient();
  const [token, setToken] = useState("");
  const [label, setLabel] = useState("");
  const signIn = useMutation({
    mutationFn: () => adminApi.signIn(token, label.trim() || "admin"),
    onSuccess: (me) => {
      setToken(""); // never kept in the page once used
      qc.setQueryData(["admin", "me"], me);
    },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (token) signIn.mutate();
  };
  return (
    <Centered title="Learning World admin">
      <form
        onSubmit={submit}
        className="flex flex-col gap-4 rounded-soft border-2 border-sand bg-white p-4"
      >
        <Field label="Admin token">
          <input
            type="password"
            autoComplete="off"
            className={inputClass}
            value={token}
            onChange={(e) => setToken(e.target.value)}
            required
          />
        </Field>
        <Field
          label="Your name for the admin log (optional)"
          hint="Shown next to every change you make."
        >
          <input
            className={inputClass}
            maxLength={32}
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder="admin"
          />
        </Field>
        <ErrorNote error={signIn.error} />
        <SmallButton type="submit" tone="primary" disabled={!token || signIn.isPending}>
          {signIn.isPending ? "Signing in…" : "Sign in"}
        </SmallButton>
        <p className="text-small text-ink/70">The session lasts 8 hours on this browser.</p>
      </form>
    </Centered>
  );
}

function Shell({ me }: { me: AdminMe }) {
  const qc = useQueryClient();
  const signOut = useMutation({
    mutationFn: adminApi.signOut,
    onSettled: () => qc.removeQueries({ queryKey: ["admin"] }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["admin", "me"] }),
  });
  return (
    <div className="md:flex md:min-h-screen">
      <aside className="border-b-2 border-sand bg-white md:w-56 md:shrink-0 md:border-b-0 md:border-e-2">
        <div className="flex items-center justify-between gap-2 px-4 py-3">
          <span className="font-heading text-h3">LW admin</span>
          <span className="text-small text-ink/70 md:hidden">{me.actor}</span>
        </div>
        <nav
          aria-label="Admin sections"
          className="flex gap-1 overflow-x-auto px-2 pb-2 md:flex-col md:overflow-visible"
        >
          {NAV.map((item) => (
            <NavLink
              key={item.path}
              to={`/admin/${item.path}`}
              className={({ isActive }) =>
                cx(
                  "flex min-h-11 shrink-0 items-center rounded-soft px-3 text-small font-semibold",
                  isActive ? "bg-primary text-white" : "text-ink hover:bg-whitewash",
                )
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="hidden flex-col gap-2 px-4 py-4 text-small md:flex">
          <span>
            Signed in as <strong>{me.actor}</strong>
          </span>
          <SmallButton onClick={() => signOut.mutate()}>Sign out</SmallButton>
        </div>
      </aside>
      <main className="min-w-0 flex-1 px-4 py-4 md:px-6">
        <Routes>
          <Route index element={<Navigate to={HOME} replace />} />
          {NAV.map((item) => (
            <Route key={item.path} path={`${item.path}/*`} element={item.element} />
          ))}
          <Route path="*" element={<Navigate to={`/admin/${HOME}`} replace />} />
        </Routes>
        <div className="mt-8 md:hidden">
          <SmallButton onClick={() => signOut.mutate()}>Sign out</SmallButton>
        </div>
      </main>
    </div>
  );
}
