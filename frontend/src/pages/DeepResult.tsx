import React from "react";
import DeepAnalysisCard from "../components/DeepAnalysisCard";

const DeepResult: React.FC = () => {

  const chunkData = [
    {
      method: "Hybrid Retrieval",
      aiModel: "GPT-4o",
      answer:
        "The Battle of Surabaya was a major armed conflict in November 1945, marking a turning point in Indonesia’s struggle for independence.",
  
      retrievedChunks: [
        {
          id: 1,
          label: "Chunk 1",
          text:
            "The Battle of Surabaya occurred in November 1945 and involved Indonesian militias resisting British-led Allied troops.",
        },
        {
          id: 2,
          label: "Chunk 2",
          text:
            "The conflict resulted in heavy casualties and is commemorated annually as Heroes’ Day in Indonesia.",
        },
      ],
  
      modelAgreement: [
        { modelName: "OpenAI", status: "AGREE" },
        { modelName: "Claude", status: "AGREE" },
        { modelName: "Gemini", status: "NEUTRAL" },
      ],
  
      evaluationMetrics: [
        { label: "MRR@5", value: 0.85 },
        { label: "Precision@3", value: 0.66 },
        { label: "Recall@3", value: 0.75 },
      ],
    },
  
    {
      method: "Dense Retrieval",
      aiModel: "Claude 3.5 Sonnet",
      answer:
        "The Surabaya conflict demonstrated Indonesia’s determination to resist colonial reoccupation after World War II.",
  
      retrievedChunks: [
        {
          id: "doc-7-1",
          label: "Historical Context",
          text:
            "Following Japan’s surrender, Indonesian forces resisted attempts by Allied troops to restore Dutch colonial control.",
        },
      ],
  
      modelAgreement: [
        { modelName: "OpenAI", status: "AGREE" },
        { modelName: "Gemini", status: "DISAGREE" },
      ],
  
      evaluationMetrics: [
        { label: "Recall@5", value: 0.92 },
      ],
    },
  
    {
      method: "Keyword Search",
      aiModel: "GPT-4.1 Mini",
      answer:
        "Heroes’ Day in Indonesia commemorates those who fought in the Battle of Surabaya in 1945.",
  
      retrievedChunks: [
        {
          id: 101,
          text:
            "November 10 is observed as Heroes’ Day in Indonesia to honor the Battle of Surabaya.",
        },
        {
          id: 102,
          label: "Casualties",
          text:
            "Thousands of Indonesian fighters and civilians were killed during the conflict.",
        },
      ],
    },
  ];


  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {chunkData.map((item, index) => {
          const normalizedItem = {
            ...item,
            retrievedChunks: item.retrievedChunks?.map((chunk: any) => ({
              ...chunk,
              id: typeof chunk.id === 'string' || typeof chunk.id === 'number' ? chunk.id : String(chunk.id),
              label: chunk.label || '', 
            })) ?? [],
            modelAgreement: item.modelAgreement
              ? item.modelAgreement.map((ma: any) => ({
                  modelName: ma.modelName,
                  status:
                    ma.status === 'AGREE' || ma.status === 'NEUTRAL' || ma.status === 'DISAGREE'
                      ? ma.status
                      : 'NEUTRAL',
                }))
              : [],
          };
          return (
            <div key={index} className="overflow-hidden">
              <DeepAnalysisCard
                {...normalizedItem}
              />
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default DeepResult;