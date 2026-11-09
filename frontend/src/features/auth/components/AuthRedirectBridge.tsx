import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { setUnauthorizedHandler } from "../lib/unauthorized";

/**
 * Lets non-React code (the axios interceptor, the SSE client) send the user
 * to sign in with an in-app navigation instead of a full page load.
 */
const AuthRedirectBridge = () => {
  const navigate = useNavigate();
  useEffect(() => {
    setUnauthorizedHandler((loginPath) => navigate(loginPath, { replace: true }));
    return () => setUnauthorizedHandler(null);
  }, [navigate]);
  return null;
};

export default AuthRedirectBridge;
