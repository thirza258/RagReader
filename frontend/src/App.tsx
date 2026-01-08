import { Router, Routes, Route } from "react-router-dom";
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

function App() {
  return (
      <Routes>


        <Route element={<LandingPageLayout />}>
          <Route path="/" element={<LandingPage />} />
        </Route>

        {/* Chat */}
        <Route element={<ChatLayout />}>
          <Route path="/chat" element={<Chatbot />} />
        </Route>

        {/* Deep Result */}
        <Route element={<DeepResultLayout />}>
          <Route
            path="/deep-result/:conversationId"
            element={<DeepResult />}
          />
        </Route>

        {/* Deep Analysis */}
        <Route element={<DeepResultLayout />}>
          <Route path="/deep-result" element={<DeepResult />} />
        </Route>

        {/* Login */}
        <Route element={<LoginPageLayout />}>
          <Route path="/login" element={<LoginPage />} />
        </Route>

      </Routes>
  );
}

export default App;
