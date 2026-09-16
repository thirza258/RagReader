import { lazy, Suspense } from "react";
import { Routes, Route } from "react-router-dom";
import {
  ChatLayout,
  LandingPageLayout,
  LoginPageLayout,
  DeepResultLayout
} from "./layout/_layout";

import LandingPage from "./pages/LandingPage";
import Chatbot from "./pages/Chatbot";
import DeepResult from "./pages/DeepResult";
import LoginPage from "./pages/LoginPage";
import ErrorPage from "./pages/ErrorPage";
import LoadingPage from "./pages/LoadingPage";
import GroundTruthSelector from "./pages/GroundTruth";
import Docs from "./pages/Docs";

const Courses = lazy(() => import("./pages/Courses"));
const coursePage = (
  <Suspense fallback={<main className="container mx-auto px-6 pt-28" role="status">Loading courses…</main>}>
    <Courses />
  </Suspense>
);

function App() {
  return (
      <Routes>
        <Route element={<LandingPageLayout />}>
          <Route path="/" element={<LandingPage />} />
        </Route>

        <Route element={<ChatLayout />}>
          <Route path="/chat" element={<Chatbot />} />
        </Route>

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
          <Route path="/loading" element={<LoadingPage />} />
        </Route>

        <Route element={<LandingPageLayout />}>
          <Route
            path="/ground-truth/:conversationId/:documentId"
            element={<GroundTruthSelector />}
          />
        </Route>

        <Route element={<LandingPageLayout />}>
          <Route path="/docs" element={<Docs />} />
          <Route path="/courses/:courseId?/:lessonId?" element={coursePage} />
          <Route path="/courses/*" element={coursePage} />
        </Route>

      </Routes>
  );
}

export default App;
