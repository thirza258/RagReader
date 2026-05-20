import axios from "axios";

const BASE_URL = import.meta.env.VITE_API_URL;
const API_VERSION = import.meta.env.VITE_API_VERSION || "v1";

export const WS_URL = import.meta.env.VITE_WS_URL || BASE_URL.replace(/^http/, "ws");

export const apiClient = axios.create({
    baseURL: `${BASE_URL}/api/${API_VERSION}`,
    timeout: 30000,
});

