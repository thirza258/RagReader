import React, { useState, useEffect } from "react";
import service from "../services/service";
import { TaskData } from "../interface";

interface GroundTruthResponseProps {
  conversationId: string;
  groundTruth: string;
  setGroundTruth: (val: string) => void;
}

const GroundTruthResponse: React.FC<GroundTruthResponseProps> = ({
  conversationId,
  groundTruth,
  setGroundTruth,
}) => {
  const [taskData, setTaskData] = useState<TaskData | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const[fetchError, setFetchError] = useState("");

  useEffect(() => {
    const fetchTaskDetails = async () => {
      setIsLoading(true);
      try {
        if (conversationId) {
          const response = await service.getConversation(conversationId);
          if (!response.data) {
            setFetchError("No conversation found.");
            return;
          }
          setTaskData({
            id: conversationId,
            prompt: response.data.query,
          });
        }
      } catch {
        setFetchError("Failed to load task details.");
      } finally {
        setIsLoading(false);
      }
    };
    fetchTaskDetails();
  },[conversationId]);

  if (isLoading)
    return <div className="p-4 text-muted-foreground">Loading task details...</div>;
  if (fetchError)
    return <div className="p-4 text-red-500">{fetchError}</div>;

  return (
    <div className="flex flex-col gap-4">

      <div className="bg-muted/30 p-4 rounded-lg border border-border/50">
        <h3 className="text-sm font-semibold mb-2">Original Prompt</h3>
        <p className="text-base text-foreground mb-3">{taskData?.prompt}</p>
      </div>

      <div>
        <label
          htmlFor="groundTruth"
          className="block mb-2 text-sm font-semibold text-foreground"
        >
          Ground Truth Answer:
        </label>
        <textarea
          id="groundTruth"
          rows={6}
          value={groundTruth}
          onChange={(e) => setGroundTruth(e.target.value)}
          placeholder="Type the expected perfect response here..."
          className="w-full p-3 rounded-md border border-input bg-background text-foreground text-sm focus:outline-none focus:ring-1 focus:ring-primary transition-shadow resize-y"
        />
      </div>
    </div>
  );
};

export default GroundTruthResponse;