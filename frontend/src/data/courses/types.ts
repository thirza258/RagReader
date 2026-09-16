export interface Lesson {
  id: string;
  title: string;
  summary: string;
  minutes: number;
  moduleId?: string;
  objectives: string[];
  content: string;
  exercise: { title: string; steps: string[]; solution: string };
  quiz: { question: string; options: string[]; answer: number; explanation: string };
  sources?: { title: string; url: string }[];
}

export interface Course {
  id: string;
  title: string;
  description: string;
  level: "Beginner" | "Intermediate" | "Advanced";
  category: "Fundamentals" | "RAG modules" | "Evaluation" | "Practice";
  prerequisites: string;
  outcomes: string[];
  lessons: Lesson[];
}
