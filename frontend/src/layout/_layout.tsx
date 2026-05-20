import NavBar from "../components/Navbar";
import Sidebar from "../components/Sidebar";
import { Outlet } from "react-router-dom";
import DeepSidebar from "../components/DeepSidebar";
import { DeepResultContextType } from "../types/types";

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
  const[sharedIds, setSharedIds] = useState<{ conversationId: string | null; documentId: string | null }>({
    conversationId: null,
    documentId: null,
  });

  return (
    <div className="flex flex-col h-screen overflow-hidden">
      <NavBar /> 
      <div className="flex flex-1 overflow-hidden pt-16">
        <DeepSidebar
        conversationId={sharedIds.conversationId}
        documentId={sharedIds.documentId}
        onBack={function (): void {
          throw new Error("Function not implemented.");
        } } onAnalyze={function (): void {
          throw new Error("Function not implemented.");
        } } />
        <main className="flex-1 overflow-y-auto relative ps-5">
           <Outlet context={{ setIds: setSharedIds } satisfies DeepResultContextType}/>
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

