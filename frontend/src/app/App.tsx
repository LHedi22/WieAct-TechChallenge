import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { createBrowserRouter, Navigate, RouterProvider } from "react-router-dom";
import { StyleguidePage } from "@/features/styleguide/StyleguidePage";
import { useDocumentLanguage } from "./useDocumentLanguage";

const router = createBrowserRouter([
  // M0: no landing yet (M3), so the root shows the design system.
  { path: "/", element: <Navigate to="/styleguide" replace /> },
  { path: "/styleguide", element: <StyleguidePage /> },
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
