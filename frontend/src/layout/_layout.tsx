import NavBar from "../components/Navbar";
import Sidebar from "../components/Sidebar";
import { Outlet, useNavigate } from "react-router-dom";
import DeepSidebar, { AnalysisRunState } from "../components/DeepSidebar";
import { AnalysisRequest, DeepResultContextType } from "../types/types";

import { useState } from "react";

const ChatLayout = () => {


  return (
    <div className="flex flex-col h-screen overflow-hidden">
      <NavBar />
      <div className="flex flex-1 overflow-hidden pt-16">
        <Sidebar />
        <main className="flex-1 overflow-y-auto bg-gray-100 relative">
           <Outlet />
        </main>
      </div>
    </div>
  );
};

const LandingPageLayout = () => {
  return (
    <>
      <NavBar />
      <Outlet />
    </>
  );
};


const LoginPageLayout = () => {
  return (
    <>
      <Outlet />
    </>
  );
};

const DeepResultLayout = () => {
  const navigate = useNavigate();

  const [sharedIds, setSharedIds] = useState<{
    conversationId: string | null;
    documentId: string | null;
  }>({ conversationId: null, documentId: null });

  // The sidebar owns the config; DeepResult owns the WebSocket. These three
  // pieces of state are the whole conversation between them.
  const [analysisRequest, setAnalysisRequest] = useState<AnalysisRequest | null>(null);
  const [stopSignal, setStopSignal] = useState(0);
  const [runState, setRunState] = useState<AnalysisRunState>({
    isRunning: false,
    completed: 0,
    total: 0,
  });

  return (
    <div className="flex flex-col h-screen overflow-hidden">
      <NavBar />
      <div className="flex flex-1 overflow-hidden pt-16">
        <DeepSidebar
          conversationId={sharedIds.conversationId}
          documentId={sharedIds.documentId}
          runState={runState}
          onBack={() => navigate(-1)}
          onAnalyze={(config) =>
            // A fresh nonce is what makes pressing Run twice with the same
            // config start two runs instead of being ignored as unchanged.
            setAnalysisRequest({ config, nonce: Date.now() })
          }
          onStop={() => setStopSignal((n) => n + 1)}
        />
        <main className="flex-1 overflow-y-auto relative ps-5">
           <Outlet
             context={{
               setIds: setSharedIds,
               analysisRequest,
               stopSignal,
               setRunState,
             } satisfies DeepResultContextType}
           />
        </main>
      </div>
    </div>
  );
};

export {
    ChatLayout,
    LandingPageLayout,
    LoginPageLayout,
    DeepResultLayout
};
