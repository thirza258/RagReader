import NavBar from "../components/Navbar";
import Sidebar from "../components/Sidebar";
import { Outlet, useNavigate, useParams } from "react-router-dom";
import DeepSidebar, { AnalysisRunState } from "../components/DeepSidebar";
import { AnalysisRequest, DeepResultContextType } from "../types/types";

import { useState } from "react";
import type { AnalysisConfigOptions } from "../interface";

const ChatLayout = () => {


  return (
    <div className="flex flex-col h-screen overflow-hidden">
      <NavBar />
      <div className="flex flex-1 overflow-hidden pt-16">
        <Sidebar />
        <main className="relative flex-1 overflow-y-auto bg-background">
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
  const { conversationId } = useParams();
  return <DeepResultWorkspace key={conversationId} />;
};

const DeepResultWorkspace = () => {
  const navigate = useNavigate();

  const [sharedIds, setSharedIds] = useState<{
    conversationId: string | null;
    documentId: string | null;
  }>({ conversationId: null, documentId: null });

  // The sidebar owns the config; DeepResult owns the WebSocket. These three
  // pieces of state are the whole conversation between them.
  const [analysisRequest, setAnalysisRequest] = useState<AnalysisRequest | null>(null);
  const [stopSignal, setStopSignal] = useState(0);
  const [modulesAvailable, setModulesAvailable] = useState(false);
  const [selectedModules, setSelectedModules] = useState<string[]>([]);
  const [analysisOptions, setAnalysisOptions] = useState<AnalysisConfigOptions | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [runState, setRunState] = useState<AnalysisRunState>({
    isRunning: true,
    completed: 0,
    total: 0,
  });

  return (
    <div className="flex flex-col h-screen overflow-hidden">
      <NavBar />
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden pt-16">
        <div className="flex shrink-0 items-center justify-between gap-3 border-b border-border px-4 py-2 md:hidden">
          <button id="analysis-settings-toggle" type="button" aria-expanded={settingsOpen} aria-controls="analysis-settings" onClick={() => setSettingsOpen((open) => !open)} className="border border-input px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">{settingsOpen ? "View analysis flow" : "Analysis settings"}</button>
          {runState.isRunning && <button type="button" onClick={() => setStopSignal((n) => n + 1)} className="px-2 py-2 text-sm text-destructive focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">Stop analysis</button>}
        </div>
        <div className="flex min-h-0 flex-1 overflow-hidden">
          <div id="analysis-settings" className={`${settingsOpen ? "block" : "hidden"} min-h-0 w-full flex-1 md:block md:w-1/3 md:min-w-[320px] md:max-w-[380px] md:flex-none`}>
            <DeepSidebar
              conversationId={sharedIds.conversationId}
              documentId={sharedIds.documentId}
              runState={runState}
              modulesAvailable={modulesAvailable}
              selectedModules={selectedModules}
              onModulesChange={setSelectedModules}
              onOptionsLoaded={setAnalysisOptions}
              onBack={() => navigate(-1)}
              onAnalyze={(config) => {
                // A fresh nonce is what makes pressing Run twice with the same
                // config start two runs instead of being ignored as unchanged.
                setAnalysisRequest({ config, nonce: Date.now() });
                setSettingsOpen(false);
                document.getElementById("analysis-settings-toggle")?.focus();
              }}
              onStop={() => setStopSignal((n) => n + 1)}
            />
          </div>
          <main className={`${settingsOpen ? "hidden" : "block"} relative min-w-0 flex-1 overflow-y-auto bg-background px-4 py-6 md:block lg:px-6`}>
             <Outlet
               context={{
                 setIds: setSharedIds,
                 analysisRequest,
                 stopSignal,
                 setRunState,
                 runState,
                 analysisOptions,
                 setModulesAvailable,
                 setSelectedModules,
               } satisfies DeepResultContextType}
             />
          </main>
        </div>
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
