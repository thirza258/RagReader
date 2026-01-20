import axios from "axios";

const BASE_URL = import.meta.env.VITE_API_URL;
const API_VERSION = import.meta.env.VITE_API_VERSION || "v1";

export const apiClient = axios.create({
    baseURL: `${BASE_URL}/api/${API_VERSION}`,
    timeout: 30000,
});
