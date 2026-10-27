import { useTranslation } from "react-i18next";
import { useUiStore } from "@/app/uiStore";
import { dirFor, LANGUAGES } from "@/i18n/languages";
import { cx } from "./cx";

/** Each language is labelled in itself, so anyone can find theirs. */
export function LanguageSwitcher({ className }: { className?: string }) {
  const { t } = useTranslation();
  const language = useUiStore((s) => s.language);
  const setLanguage = useUiStore((s) => s.setLanguage);
  return (
    <div
      role="group"
      aria-label={t("language.label")}
      className={cx("flex flex-wrap gap-2", className)}
    >
      {LANGUAGES.map((lang) => (
        <button
          key={lang}
          type="button"
          lang={lang}
          dir={dirFor(lang)}
          aria-pressed={language === lang}
          onClick={() => setLanguage(lang)}
          className={cx(
            "min-h-11 rounded-pixel-step border-2 px-3 py-1 font-semibold",
            language === lang
              ? "border-ink bg-primary text-white"
              : "border-sand bg-white text-ink",
          )}
        >
          {t(`language.${lang}`)}
        </button>
      ))}
    </div>
  );
}
