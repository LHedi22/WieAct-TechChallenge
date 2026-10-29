import { api, type Me } from "@/api/client";

/** Where a signed-in student goes next: onboarding → their latest world → create or join. */
export async function homePath(me: Me): Promise<string> {
  if (!me.onboarded) return "/welcome";
  if (!me.has_worlds) return "/worlds/new";
  const worlds = await api.myWorlds();
  return worlds[0] ? `/worlds/${worlds[0].id}` : "/worlds/new";
}
