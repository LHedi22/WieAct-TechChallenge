import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "@/app/App";
import { useUiStore } from "@/app/uiStore";
import { i18nReady, initI18n } from "@/i18n";
import "@/styles/index.css";

initI18n(useUiStore.getState().language);

// First paint in the student's language (its locale chunk is fetched first, audit OPT-21).
void i18nReady().finally(() =>
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  ),
);
