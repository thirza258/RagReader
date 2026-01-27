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

        <Route element={<DeepResultLayout />}>
          <Route path="/deep-result" element={<DeepResult />} />
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

      </Routes>
  );
}

export default App;
