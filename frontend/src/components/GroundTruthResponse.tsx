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
    return <p className="p-4 text-sm text-muted-foreground">Loading task details…</p>;
  if (fetchError)
    return <p className="p-4 text-sm text-destructive">{fetchError}</p>;

  return (
    <div className="flex flex-col gap-4">

      <div className="border-l-2 border-border py-1 pl-4">
        <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Original question
        </h3>
        <p className="prose-note mt-1 text-base">{taskData?.prompt}</p>
      </div>

      <div>
        <label htmlFor="groundTruth" className="mb-1.5 block text-sm font-medium">
          Expected answer
        </label>
        <textarea
          id="groundTruth"
          rows={6}
          value={groundTruth}
          onChange={(e) => setGroundTruth(e.target.value)}
          placeholder="Write the answer you would consider correct…"
          className="w-full resize-y border border-input bg-background p-3 text-sm outline-none transition-colors placeholder:text-muted-foreground focus:border-primary"
        />
      </div>
    </div>
  );
};

export default GroundTruthResponse;