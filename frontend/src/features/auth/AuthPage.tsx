import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, type ApiError, type Me } from "@/api/client";
import { homePath } from "@/app/home";
import { useUiStore } from "@/app/uiStore";
import { Input, LanguageSwitcher, PixelButton, PixelPanel, Sprite } from "@/components";

const MIN_PASSWORD = 8; // same rule as the server (errors.password_short)

/** /signup and /signin — a nickname and a password, nothing else (no e-mail, no real name). */
export function AuthPage({ mode }: { mode: "signup" | "signin" }) {
  const { t } = useTranslation("auth");
  const { t: tc } = useTranslation();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const qc = useQueryClient();
  const language = useUiStore((s) => s.language);
  const [nickname, setNickname] = useState("");
  const [password, setPassword] = useState("");
  const [touched, setTouched] = useState(false);

  const submit = useMutation({
    mutationFn: (): Promise<Me> =>
      mode === "signup"
        ? api.signup(nickname.trim(), password, language)
        : api.login(nickname.trim(), password),
    onSuccess: async (me) => {
      qc.setQueryData(["me"], me);
      const next = params.get("next");
      void navigate(next && next.startsWith("/") ? next : await homePath(me), { replace: true });
    },
  });

  const tooShort = mode === "signup" && password.length < MIN_PASSWORD;
  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    setTouched(true);
    if (!nickname.trim() || !password || tooShort) return;
    submit.mutate();
  };
  const serverError = submit.error ? tc((submit.error as ApiError).key) : undefined;

  return (
    <div className="flex min-h-screen flex-col">
      <header className="flex flex-wrap items-center justify-between gap-3 px-4 py-4 sm:px-8">
        <Link to="/" className="flex items-center gap-2 font-heading text-h3">
          <Sprite name="island" scale={1} />
          {tc("app.name")}
        </Link>
        <LanguageSwitcher />
      </header>
      <main className="mx-auto flex w-full max-w-md flex-1 items-start px-4 py-8">
        <PixelPanel className="flex w-full flex-col gap-5 p-6">
          <h1 className="text-h1">{t(`${mode}.title`)}</h1>
          <form onSubmit={onSubmit} className="flex flex-col gap-4" noValidate>
            <div className="flex flex-col gap-1">
              <Input
                label={t("nickname")}
                value={nickname}
                onChange={(e) => setNickname(e.target.value)}
                autoComplete="username"
                maxLength={32}
                spellCheck={false}
                error={touched && !nickname.trim() ? t("nicknameRequired") : undefined}
              />
              {mode === "signup" && <p className="text-small text-ink/70">{t("nicknameHelp")}</p>}
            </div>
            <div className="flex flex-col gap-1">
              <Input
                label={t("password")}
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete={mode === "signup" ? "new-password" : "current-password"}
                error={
                  touched && (tooShort || !password)
                    ? t("passwordHelp", { min: MIN_PASSWORD })
                    : undefined
                }
              />
              {mode === "signup" && !touched && (
                <p className="text-small text-ink/70">{t("passwordHelp", { min: MIN_PASSWORD })}</p>
              )}
            </div>
            {serverError && (
              <p role="alert" className="text-small text-danger">
                {serverError}
              </p>
            )}
            <PixelButton type="submit" variant="spend" disabled={submit.isPending}>
              {t(`${mode}.submit`)}
            </PixelButton>
          </form>
          <p className="text-small">
            {t(`${mode}.other`)}{" "}
            <Link
              to={mode === "signup" ? "/signin" : "/signup"}
              className="font-semibold text-primary underline"
            >
              {t(`${mode}.otherLink`)}
            </Link>
          </p>
        </PixelPanel>
      </main>
    </div>
  );
}
