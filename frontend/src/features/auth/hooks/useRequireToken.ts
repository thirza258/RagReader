import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { loginPathFor } from "../lib/redirect";
import { getToken } from "../lib/session";

/**
 * The bearer token for pages that need the workspace API. Without one —
 * including a user remembered only by username from before tokens existed —
 * the user is sent to sign in and brought back here afterwards.
 */
export function useRequireToken(): string | null {
  const [token] = useState(() => getToken());
  const location = useLocation();
  const navigate = useNavigate();

  useEffect(() => {
    if (!token) navigate(loginPathFor(`${location.pathname}${location.search}`), { replace: true });
  }, [token, navigate, location.pathname, location.search]);

  return token;
}
