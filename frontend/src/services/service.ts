import { apiClient } from "./apiClient";

const signUp = async (email: string, username: string) => {
    const response = await apiClient.post("/sign-up/", {
        "USERNAME": username,
        "EMAIL": email,
    },
    {
        headers: {
            "Content-Type": "application/json",
        },
    });
    return response.data;
};

const submitFile = async (
    file: File,
    username: string
) => {
    const formData = new FormData();
    formData.append("FILE", file);
    formData.append("USER", username);

    const response = await apiClient.post("/insert-data/", formData, {
        headers: {
            "Content-Type": "multipart/form-data",
        },
    });

    return response.data;
};

const submitURL = async (
    url: string,
    username: string
) => {
    const response = await apiClient.post(
        "/insert-url/",
        {
            URL: url,
            USER: username,
        },
        {
            headers: {
                "Content-Type": "application/json",
            },
        }
    );

    return response.data;
};

const submitText = async (
    text: string,
    username: string
) => {
    const response = await apiClient.post("/insert-text/", {
        TEXT: text,
        USER: username,
    },
    {
        headers: {
            "Content-Type": "application/json",
        },
    }
);

    return response.data;
};

const generateChat = async (
    query: string,
    username: string
) => {
    const response = await apiClient.post("/query/", {
        QUERY: query,
        USER: username,
    });

    return response.data;
};

const openChat = async (
    username: string
) => {
    const response = await apiClient.post("/open-chat/", {
        USER: username,
    });
    return response.data;
};

const getJobStatus = async (
    jobId: string
) => {
    const response = await apiClient.get(`/job-status/${jobId}/`);
    return response.data;
};


const cleanSystem = async () => {
    const response = await apiClient.get("/clean/");
    return response.data;
};

export default {
    submitFile,
    submitURL,
    generateChat,
    cleanSystem,
    signUp,
    submitText,
    openChat,
    getJobStatus,
};
