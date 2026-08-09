import { apiClient } from "./apiClient";
import type {
  AnalysisConfigOptions,
  CandidatePoolResponse,
  DeepAnalysisConfig,
  GroundTruthChunkResponse,
  StartAnalysisResponse,
} from "../interface";


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

const startDeepAnalysis = async (
    conversation_id: string,
    config?: Partial<DeepAnalysisConfig>
): Promise<StartAnalysisResponse> => {
    const response = await apiClient.post("/start-analysis/", {
        conversation_id,
        // Omitted entirely when unset so the backend applies its own defaults
        // (the full method × model matrix) rather than an empty selection.
        ...(config ? { config } : {}),
    });
    return response.data;
}

const getAnalysisConfig = async (): Promise<AnalysisConfigOptions> => {
    const response = await apiClient.get("/analysis-config/");
    return response.data;
}




const cleanSystem = async () => {
    const response = await apiClient.get("/clean/");
    return response.data;
};

const jsonConfig = {
  headers: {
    "Content-Type": "application/json",
    "Accept": "application/json",
  },
};

const createChunk = async (username: string) => {
  const response = await apiClient.post(
    "/chunk/",
    { USER: username },
    jsonConfig
  );
  return response.data;
};

const getChunk = async (document_id: string) => {
  const response = await apiClient.get(
    `/chunk/${document_id}/`,
    jsonConfig
  );
  return response.data;
};

const CreateGroundTruthChunk = async (
  conversation_id: string,
  chunk_id: string[]
) => {
  const response = await apiClient.post(
    "/ground-truth-chunk/",
    {
      conversation_id,
      chunk_id,
    },
    jsonConfig
  );
  return response.data;
};

const CreateGroundTruthResponse = async (
  conversation_id: string,
  response: string
) => {
  const responseData = await apiClient.post(
    "/ground-truth-response/",
    {
      conversation_id,
      response,
    },
    jsonConfig
  );
  return responseData.data;
};

/**
 * Derives the ground-truth chunks by running the query through every
 * retrieval method and fusing the rankings with RRF. Replaces whatever
 * ground truth the conversation had.
 */
const poolGroundTruthChunks = async (
  conversation_id: string,
  options?: { top_n?: number; rrf_k?: number }
): Promise<CandidatePoolResponse> => {
  const response = await apiClient.post(
    "/ground-truth-chunk/pool/",
    { conversation_id, ...options },
    jsonConfig
  );
  return response.data;
};

const getGroundTruthChunk = async (
  conversation_id: string
): Promise<GroundTruthChunkResponse> => {
  const response = await apiClient.get(
    `/ground-truth-chunk/${conversation_id}/`,
    jsonConfig
  );
  return response.data;
};

const PostChunkEvaluationResult = async (
  conversation_id: string,
  chunk_id: string[]
) => {
  const response = await apiClient.post(
    "/evaluate/ground-truth-chunk/",
    {
      conversation_id,
      retrieved_chunk_id: chunk_id,
    },
    jsonConfig
  );
  return response.data;
};

const PostResponseEvaluationResult = async (
  conversation_id: string,
  response: string
) => {
  const responseData = await apiClient.post(
    "/evaluate/ground-truth-response/",
    {
      conversation_id,
      response,
    },
    jsonConfig
  );
  return responseData.data;
};

const getConversation = async (conversation_id: string) => {
  const response = await apiClient.get(
    `/conversation/${conversation_id}/`,
    jsonConfig
  );
  return response.data;
};

const getDocumentInfo = async (username: string) => {
  const response = await apiClient.get(
    `/document/${username}/`,
    jsonConfig
  );
  return response.data;
}

const getConversationHistory = async (username: string) => {
  const response = await apiClient.get(
    `/conversation-history/${username}/`,
    jsonConfig
  );
  return response.data;
}


export default {
    submitFile,
    submitURL,
    generateChat,
    cleanSystem,
    signUp,
    submitText,
    openChat,
    getJobStatus,
    startDeepAnalysis,
    getAnalysisConfig,
    createChunk,
    CreateGroundTruthChunk,
    CreateGroundTruthResponse,
    poolGroundTruthChunks,
    getGroundTruthChunk,
    PostChunkEvaluationResult,
    PostResponseEvaluationResult,
    getChunk,
    getConversation,
    getDocumentInfo,
    getConversationHistory
};
