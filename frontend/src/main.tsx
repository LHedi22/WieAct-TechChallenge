import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "@/app/App";
import { useUiStore } from "@/app/uiStore";
import { initI18n } from "@/i18n";
import "@/styles/index.css";

initI18n(useUiStore.getState().language);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
