import axios from "axios";
import { getToken } from "../features/auth/lib/session";
import { isProtectedApiPath, notifyUnauthorized } from "../features/auth/lib/unauthorized";

const API_BASE = import.meta.env.VITE_API_URL || "/api";
const API_VERSION = import.meta.env.VITE_API_VERSION || "v1";

/** e.g. `/api/v1`; fetch-based streaming builds its URLs from this. */
export const API_BASE_URL = `${API_BASE}/${API_VERSION}`;

export const apiClient = axios.create({
    baseURL: API_BASE_URL,
    timeout: 30000,
});

// Every endpoint except sign-in/sign-up and analysis-config authenticates
// with the token issued at sign-in, so it is sent whenever one exists.
apiClient.interceptors.request.use((config) => {
    const token = getToken();
    if (token && !config.headers.has("Authorization")) {
        config.headers.set("Authorization", `Bearer ${token}`);
    }
    return config;
});

// A 401 from a token-protected endpoint (workspace, legacy or deep analysis)
// means the token is missing or stale: sign in again and come back. Sign-in
// itself answers 401 for a wrong password, so it is not treated that way.
apiClient.interceptors.response.use(
    (response) => response,
    (error) => {
        if (error?.response?.status === 401 && isProtectedApiPath(error?.config?.url)) {
            notifyUnauthorized();
        }
        return Promise.reject(error);
    },
);
