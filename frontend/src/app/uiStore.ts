import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";
import type { Language } from "@/i18n/languages";

/** UI-only state (server state lives in TanStack Query). */
interface UiState {
  language: Language;
  reducedMotion: boolean;
  /** Dev-only identity until sign-in exists (M3): sent as X-Dev-User. */
  devUser: string;
  setLanguage: (language: Language) => void;
  setReducedMotion: (reducedMotion: boolean) => void;
  setDevUser: (devUser: string) => void;
}

/** localStorage can be missing or throw (private mode); fall back to memory. */
function safeStorage(): Storage {
  try {
    const probe = "__lw_probe__";
    window.localStorage.setItem(probe, probe);
    window.localStorage.removeItem(probe);
    return window.localStorage;
  } catch {
    const mem = new Map<string, string>();
    return {
      getItem: (k) => mem.get(k) ?? null,
      setItem: (k, v) => void mem.set(k, v),
      removeItem: (k) => void mem.delete(k),
      clear: () => mem.clear(),
      key: (i) => [...mem.keys()][i] ?? null,
      get length() {
        return mem.size;
      },
    };
  }
}

export const useUiStore = create<UiState>()(
  persist(
    (set) => ({
      language: "en",
      reducedMotion: false,
      devUser: "demo",
      setLanguage: (language) => set({ language }),
      setReducedMotion: (reducedMotion) => set({ reducedMotion }),
      setDevUser: (devUser) => set({ devUser }),
    }),
    { name: "lw-ui", storage: createJSONStorage(safeStorage) },
  ),
);
