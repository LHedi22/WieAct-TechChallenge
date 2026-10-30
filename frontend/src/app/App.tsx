import { MutationCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import { ApiError } from "@/api/client";
import { ArenaPage } from "@/features/arena/ArenaPage";
import { AuthPage } from "@/features/auth/AuthPage";
import { BuildingSoonPage } from "@/features/island/BuildingSoonPage";
import { IslandPage } from "@/features/island/IslandPage";
import { DevJobsPage } from "@/features/jobs/DevJobsPage";
import { LandingPage } from "@/features/landing/LandingPage";
import { LeaderboardPage } from "@/features/leaderboard/Leaderboard";
import { MapPage } from "@/features/map/MapPage";
import { OnboardingPage } from "@/features/onboarding/OnboardingPage";
import { PlacementPage } from "@/features/placement/PlacementPage";
import { QuizAttemptPage } from "@/features/quiz/QuizAttemptPage";
import { QuizStartPage } from "@/features/quiz/QuizStartPage";
import { StyleguidePage } from "@/features/styleguide/StyleguidePage";
import { StudioPage } from "@/features/studio/StudioPage";
import { OutOfCoinsDialog } from "@/features/wallet/OutOfCoinsDialog";
import { TutorPage, TutorStartPage } from "@/features/tutor/TutorPage";
import { AddMaterialPage } from "@/features/worlds/AddMaterialPage";
import { CreateOrJoinPage } from "@/features/worlds/CreateOrJoinPage";
import { IndexingPage } from "@/features/worlds/IndexingPage";
import { JoinPage } from "@/features/worlds/JoinPage";
import { DailyReturnPage } from "@/features/daily/DailyReturnPage";
import { RequireAuth } from "./RequireAuth";
import { useUiStore } from "./uiStore";
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
  { path: `${W}/leaderboard`, element: signedIn(<LeaderboardPage />) },
  { path: `${W}/today`, element: signedIn(<DailyReturnPage />) },
  { path: C, element: signedIn(<IslandPage />) },
  { path: `${C}/placement`, element: signedIn(<PlacementPage />) },
  { path: `${C}/quiz/new`, element: signedIn(<QuizStartPage />) },
  { path: `${C}/quiz/:attemptId`, element: signedIn(<QuizAttemptPage />) },
  { path: `${C}/tutor/new`, element: signedIn(<TutorStartPage />) },
  { path: `${C}/tutor/:sessionId`, element: signedIn(<TutorPage />) },
  { path: `${C}/arena`, element: signedIn(<ArenaPage />) },
  { path: `${C}/studio`, element: signedIn(<StudioPage />) },
  { path: `${C}/buildings/:building`, element: signedIn(<BuildingSoonPage />) },
  { path: "/styleguide", element: <StyleguidePage /> },
  // Dev-only: the M1 demo job through useJob + LoadingStages + queue/quick-mode banners.
  ...(import.meta.env.DEV ? [{ path: "/dev/jobs", element: <DevJobsPage /> }] : []),
]);

function makeQueryClient(): QueryClient {
  const qc: QueryClient = new QueryClient({
    mutationCache: new MutationCache({
      // Starts reserve coins and finishes earn points: keep the top bar's wallet current.
      onSuccess: () => void qc.invalidateQueries({ queryKey: ["wallet"] }),
      // A paid start without enough coins opens the out-of-coins screen, wherever it was (an
      // empty Class Pool is also a 402, shown where the student chose to pay from the pool).
      onError: (e) => {
        if (e instanceof ApiError && e.key === "errors.insufficient_coins")
          useUiStore.getState().setOutOfCoins(true);
      },
    }),
  });
  return qc;
}

export function App() {
  const [queryClient] = useState(makeQueryClient);
  useDocumentLanguage();
  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
      <OutOfCoinsDialog />
    </QueryClientProvider>
  );
}
