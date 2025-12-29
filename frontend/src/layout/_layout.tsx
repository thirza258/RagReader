// layouts/MainLayout.jsx
import NavBar from "../components/Navbar";
import Sidebar from "../components/Sidebar";
import { Outlet } from "react-router-dom";

const ChatLayout = () => {
  return (
    <>
      <NavBar />
      <Sidebar />
      <Outlet />
    </>
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
  return (
    <>
      <NavBar />
      <Outlet />
    </>
  );
};

export { 
    ChatLayout, 
    LandingPageLayout,
    LoginPageLayout,
    DeepResultLayout 
};

