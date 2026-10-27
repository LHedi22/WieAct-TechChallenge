import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { I18nextProvider } from "react-i18next";
import { MemoryRouter } from "react-router-dom";
import i18n from "@/i18n";
import type { Language } from "@/i18n/languages";

/** Renders with router + an i18n instance in the given language. */
export function renderWith(
  ui: ReactElement,
  { lang = "en", route = "/" }: { lang?: Language; route?: string } = {},
) {
  const instance = i18n.cloneInstance({ lng: lang });
  return render(
    <I18nextProvider i18n={instance}>
      <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>
    </I18nextProvider>,
  );
}
