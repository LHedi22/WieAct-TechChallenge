import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { createBrowserRouter, Navigate, RouterProvider } from "react-router-dom";
import { DevJobsPage } from "@/features/jobs/DevJobsPage";
import { StyleguidePage } from "@/features/styleguide/StyleguidePage";
import { useDocumentLanguage } from "./useDocumentLanguage";

const router = createBrowserRouter([
  // No landing yet (M3), so the root shows the design system.
  { path: "/", element: <Navigate to="/styleguide" replace /> },
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
