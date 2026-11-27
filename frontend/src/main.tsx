import { lazy, StrictMode, Suspense } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, Navigate, RouterProvider } from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "@fontsource-variable/inter";
import "@fontsource-variable/jetbrains-mono";
import "@fontsource/noto-sans-thai/thai-400.css";
import "@fontsource/noto-sans-thai/thai-500.css";
import "@fontsource/noto-sans-thai/thai-600.css";
import "./index.css";
import { Layout } from "./components/Layout";
import { ChatProvider } from "./hooks/chatContext";
import { ChatPage } from "./pages/ChatPage";
import { DeviceListPage } from "./pages/DeviceListPage";

// The dashboard pulls in ECharts; load it on demand to keep the initial bundle small.
const FiberPage = lazy(() => import("./pages/FiberPage").then((m) => ({ default: m.FiberPage })));
const HealthListPage = lazy(() => import("./pages/HealthListPage").then((m) => ({ default: m.HealthListPage })));
const InterfacesPage = lazy(() => import("./pages/InterfacesPage").then((m) => ({ default: m.InterfacesPage })));
const BoardsPage = lazy(() => import("./pages/BoardsPage").then((m) => ({ default: m.BoardsPage })));
const AccessPage = lazy(() => import("./pages/AccessPage").then((m) => ({ default: m.AccessPage })));
const TsdbPage = lazy(() => import("./pages/TsdbPage").then((m) => ({ default: m.TsdbPage })));
const DeviceDashboard = lazy(() => import("./pages/DeviceDashboard").then((m) => ({ default: m.DeviceDashboard })));

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 30_000, refetchOnWindowFocus: false, retry: 1 } },
});

const router = createBrowserRouter([
  {
    path: "/",
    element: <ChatProvider><Layout /></ChatProvider>,
    children: [
      { index: true, element: <Navigate to="/devices" replace /> },
      { path: "devices", element: <DeviceListPage /> },
      { path: "devices/:id", element: <Suspense fallback={null}><DeviceDashboard /></Suspense> },
      { path: "interfaces", element: <Suspense fallback={null}><InterfacesPage /></Suspense> },
      { path: "boards", element: <Suspense fallback={null}><BoardsPage /></Suspense> },
      { path: "fiber", element: <Suspense fallback={null}><FiberPage /></Suspense> },
      { path: "access", element: <Suspense fallback={null}><AccessPage /></Suspense> },
      { path: "access/:accessid", element: <Suspense fallback={null}><AccessPage /></Suspense> },
      { path: "network/reboots", element: <Suspense fallback={null}><HealthListPage key="reboots" mode="reboots" /></Suspense> },
      { path: "network/unreachable", element: <Suspense fallback={null}><HealthListPage key="unreachable" mode="unreachable" /></Suspense> },
      { path: "network/unstable", element: <Suspense fallback={null}><HealthListPage key="unstable" mode="unstable" /></Suspense> },
      { path: "network/flapping", element: <Navigate to="/network/unstable" replace /> },
      { path: "metrics", element: <Suspense fallback={null}><TsdbPage /></Suspense> },
      { path: "chat", element: <ChatPage /> },
      { path: "*", element: <Navigate to="/devices" replace /> },
    ],
  },
]);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
);
