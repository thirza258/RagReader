import { lazy, Suspense } from "react";
import { Routes, Route, Navigate } from "react-router-dom";
import {
  WorkspaceLayout,
  LandingPageLayout,
  LoginPageLayout,
  DeepResultLayout
} from "./layout/_layout";

import LandingPage from "./pages/LandingPage";
import DeepResult from "./pages/DeepResult";
import LoginPage from "./pages/LoginPage";
import ErrorPage from "./pages/ErrorPage";
import GroundTruthSelector from "./pages/GroundTruth";
import Docs from "./pages/Docs";
import Legal from "./pages/Legal";
import AuthRedirectBridge from "./features/auth/components/AuthRedirectBridge";

const Courses = lazy(() => import("./pages/Courses"));
const coursePage = (
  <Suspense fallback={<main className="container mx-auto px-6 pt-28" role="status">Loading courses…</main>}>
    <Courses />
  </Suspense>
);

const WorkspacePage = lazy(() => import("./pages/WorkspacePage"));
// One element for all three workspace routes, so switching conversations
// keeps the page (and its document polling) mounted.
const workspacePage = (
  <Suspense fallback={<p className="p-6 text-sm text-muted-foreground" role="status">Loading workspace…</p>}>
    <WorkspacePage />
  </Suspense>
);

function App() {
  return (
      <>
      <AuthRedirectBridge />
      <Routes>
        <Route element={<LandingPageLayout />}>
          <Route path="/" element={<LandingPage />} />
        </Route>

        <Route element={<WorkspaceLayout />}>
          <Route path="/workspace" element={workspacePage} />
          <Route path="/workspace/:workspaceId" element={workspacePage} />
          <Route path="/workspace/:workspaceId/c/:conversationId" element={workspacePage} />
        </Route>

        {/* The single-document chat and its loading screen became the workspace. */}
        <Route path="/chat" element={<Navigate to="/workspace" replace />} />
        <Route path="/loading" element={<Navigate to="/workspace" replace />} />

        <Route element={<DeepResultLayout />}>
          <Route
            path="/deep-result/:conversationId"
            element={<DeepResult />}
          />
        </Route>

        <Route element={<LoginPageLayout />}>
          <Route path="/login" element={<LoginPage />} />
        </Route>

        <Route element={<LandingPageLayout />}>
          <Route path="/error" element={<ErrorPage />} />
        </Route>

        <Route element={<LandingPageLayout />}>
          <Route
            path="/ground-truth/:conversationId/:documentId"
            element={<GroundTruthSelector />}
          />
        </Route>

        <Route element={<LandingPageLayout />}>
          <Route path="/docs" element={<Docs />} />
          <Route path="/privacy" element={<Legal />} />
          <Route path="/terms" element={<Legal />} />
          <Route path="/courses/:courseId?/:lessonId?" element={coursePage} />
          <Route path="/courses/*" element={coursePage} />
        </Route>

      </Routes>
      </>
  );
}

export default App;
