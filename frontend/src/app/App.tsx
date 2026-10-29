import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import { AuthPage } from "@/features/auth/AuthPage";
import { BuildingSoonPage } from "@/features/island/BuildingSoonPage";
import { IslandPage } from "@/features/island/IslandPage";
import { DevJobsPage } from "@/features/jobs/DevJobsPage";
import { LandingPage } from "@/features/landing/LandingPage";
import { MapPage } from "@/features/map/MapPage";
import { OnboardingPage } from "@/features/onboarding/OnboardingPage";
import { PlacementPage } from "@/features/placement/PlacementPage";
import { StyleguidePage } from "@/features/styleguide/StyleguidePage";
import { AddMaterialPage } from "@/features/worlds/AddMaterialPage";
import { CreateOrJoinPage } from "@/features/worlds/CreateOrJoinPage";
import { IndexingPage } from "@/features/worlds/IndexingPage";
import { JoinPage } from "@/features/worlds/JoinPage";
import { RequireAuth } from "./RequireAuth";
import { useDocumentLanguage } from "./useDocumentLanguage";

const signedIn = (element: ReactNode) => <RequireAuth>{element}</RequireAuth>;
const W = "/worlds/:worldId";
const C = `${W}/courses/:courseId`;

const router = createBrowserRouter([
  { path: "/", element: <LandingPage /> },
  { path: "/signup", element: <AuthPage mode="signup" /> },
  { path: "/signin", element: <AuthPage mode="signin" /> },
  { path: "/welcome", element: signedIn(<OnboardingPage />) },
  { path: "/worlds/new", element: signedIn(<CreateOrJoinPage />) },
  { path: "/join/:code", element: signedIn(<JoinPage />) },
  { path: W, element: signedIn(<MapPage />) },
  { path: `${W}/indexing`, element: signedIn(<IndexingPage />) },
  { path: `${W}/upload`, element: signedIn(<AddMaterialPage />) },
  { path: C, element: signedIn(<IslandPage />) },
  { path: `${C}/placement`, element: signedIn(<PlacementPage />) },
  { path: `${C}/buildings/:building`, element: signedIn(<BuildingSoonPage />) },
  { path: "/styleguide", element: <StyleguidePage /> },
  // Dev-only: the M1 demo job through useJob + LoadingStages + queue/quick-mode banners.
  ...(import.meta.env.DEV ? [{ path: "/dev/jobs", element: <DevJobsPage /> }] : []),
]);

export function App() {
  const [queryClient] = useState(() => new QueryClient());
  useDocumentLanguage();
  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  );
}
