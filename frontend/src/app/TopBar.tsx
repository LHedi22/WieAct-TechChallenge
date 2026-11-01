import { useQuery } from "@tanstack/react-query";
import { useEffect, useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router-dom";
import { api } from "@/api/client";
import {
  Avatar,
  type AvatarLook,
  Bidi,
  CoinCounter,
  LanguageSwitcher,
  PointsCounter,
  RefillTimer,
  Sprite,
  StreakCounter,
} from "@/components";
import { ProviderBadge } from "@/features/jobs/ProviderBadge";
import { useMe, useSignOut, useWallet } from "@/hooks/useSession";

function useSecondsUntil(iso: string | undefined): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 30_000);
    return () => window.clearInterval(id);
  }, []);
  return iso ? Math.max(0, Math.round((Date.parse(iso) - now) / 1000)) : 0;
}

/** Logo, world switcher, dev provider badge, coins / points / streak / refill (from /api/wallet),
 * avatar menu. */
export function TopBar({ worldId }: { worldId?: string }) {
  const { t } = useTranslation("map");
  const navigate = useNavigate();
  const me = useMe().data;
  const wallet = useWallet().data;
  const worlds = useQuery({ queryKey: ["my-worlds"], queryFn: api.myWorlds }).data ?? [];
  const signOut = useSignOut();
  const [menu, setMenu] = useState(false);
  const selectId = useId();
  const refill = useSecondsUntil(wallet?.refill_at);

  return (
    <header className="flex flex-wrap items-center gap-3 border-b-2 border-sand bg-whitewash px-4 py-2 sm:px-6">
      <Link to="/" className="flex items-center gap-2 font-heading text-h3">
        <Sprite name="island" scale={1} />
        {t("common:app.name")}
      </Link>
      {worlds.length > 0 && (
        <div className="flex items-center gap-2">
          <label htmlFor={selectId} className="text-small text-ink/70">
            {t("topbar.world")}
          </label>
          <select
            id={selectId}
            value={worldId ?? ""}
            onChange={(e) =>
              void navigate(e.target.value === "new" ? "/worlds/new" : `/worlds/${e.target.value}`)
            }
            className="min-h-11 max-w-64 truncate rounded-pixel-step border-2 border-ink bg-white ps-2 pe-8 font-semibold"
          >
            {!worldId && <option value="">—</option>}
            {worlds.map((w) => (
              <option key={w.id} value={w.id}>
                {w.name}
              </option>
            ))}
            <option value="new">{t("topbar.newWorld")}</option>
          </select>
        </div>
      )}
      <div className="ms-auto flex flex-wrap items-center gap-2">
        <ProviderBadge />
        {wallet && (
          <>
            <CoinCounter value={wallet.coins} />
            <PointsCounter value={wallet.points} />
            <StreakCounter days={wallet.streak} />
            <RefillTimer seconds={refill} />
          </>
        )}
        <div className="relative">
          <button
            type="button"
            aria-expanded={menu}
            aria-haspopup="menu"
            aria-label={t("topbar.account", { nickname: me?.nickname ?? "" })}
            onClick={() => setMenu((m) => !m)}
            className="rounded-pixel-step border-2 border-ink"
          >
            <Avatar look={me?.avatar as AvatarLook | null} size={40} />
          </button>
          {menu && (
            <div
              role="menu"
              className="absolute end-0 top-full z-20 mt-2 flex w-64 flex-col gap-3 rounded-pixel-step border-2 border-ink bg-white p-3 shadow-panel"
            >
              <Bidi className="font-semibold">{me?.nickname}</Bidi>
              <LanguageSwitcher />
              <button
                type="button"
                role="menuitem"
                className="min-h-11 rounded-pixel-step border-2 border-sand text-start font-semibold ps-3"
                onClick={() =>
                  signOut.mutate(undefined, {
                    onSuccess: () => void navigate("/", { replace: true }),
                  })
                }
              >
                {t("topbar.signOut")}
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
