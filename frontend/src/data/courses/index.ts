import type { Course } from "./types.ts";
import { fundamentals } from "./fundamentals.ts";
import { queryLessons } from "./query.ts";
import { retrievalLessons } from "./retrieval.ts";
import { routingLessons } from "./routing.ts";
import { evaluationLessons } from "./evaluation.ts";
import { practiceLessons } from "./practice.ts";

export const courses: Course[] = [
  {
    id: "rag-fundamentals", title: "RAG fundamentals",
    description: "From your first document to a grounded answer. Learn chunks, embeddings, dense and sparse search, hybrid retrieval, and the reader.",
    level: "Beginner", category: "Fundamentals", prerequisites: "No RAG experience needed. Basic familiarity with asking an AI a question is enough.",
    outcomes: ["Explain the entire ingestion and question pipeline.", "Compare the three retrieval methods.", "Run and inspect your first baseline."],
    lessons: fundamentals,
  },
  {
    id: "query-methods", title: "Ask better search questions",
    description: "Explore five ways to bridge the gap between a user's question and the language of the source document.",
    level: "Intermediate", category: "RAG modules", prerequisites: "RAG fundamentals, especially dense search and grounded generation.",
    outcomes: ["Use all five query modules with a clear purpose.", "Detect query drift and hypothetical-answer contamination.", "Compare query changes using real source evidence."],
    lessons: queryLessons,
  },
  {
    id: "retrieval-methods", title: "Retrieve better evidence",
    description: "Fuse complementary rankings, search a summary tree, and expand into longer passages without losing source identity.",
    level: "Intermediate", category: "RAG modules", prerequisites: "Dense, sparse, and hybrid retrieval from the fundamentals course.",
    outcomes: ["Calculate reciprocal rank fusion.", "Explain RAPTOR and LongRAG's different retrieval units.", "Account for evidence expansion and shared context limits."],
    lessons: retrievalLessons,
  },
  {
    id: "adaptive-pipelines", title: "Route, correct, and refine",
    description: "Decide when to retrieve, check evidence quality, expand context, and search again as an answer develops.",
    level: "Advanced", category: "RAG modules", prerequisites: "RAG fundamentals and an understanding of query and retrieval modules.",
    outcomes: ["Distinguish complexity routing from evidence sufficiency.", "Trace correction and forward-looking retrieval.", "Evaluate routing errors, fallbacks, and bounded work."],
    lessons: routingLessons,
  },
  {
    id: "evaluation", title: "Ground answers and measure quality",
    description: "Add useful demonstrations, write independent references, and interpret retrieval and Ragas answer metrics.",
    level: "Intermediate", category: "Evaluation", prerequisites: "The first RAGReader experiment and grounded generation lessons.",
    outcomes: ["Use Contextual Learning without target-answer leakage.", "Calculate retrieval precision, recall, and F1.", "Diagnose support, relevance, and correctness separately."],
    lessons: evaluationLessons,
  },
  {
    id: "rag-in-practice", title: "RAG in practice",
    description: "Compose all module families, run fair experiments, consider production constraints, and defend a configuration in a capstone.",
    level: "Advanced", category: "Practice", prerequisites: "The earlier courses, including module behavior and evaluation.",
    outcomes: ["Design controlled module and combination experiments.", "Account for latency, source trust, and failure handling.", "Complete a reproducible capstone with held-out questions."],
    lessons: practiceLessons,
  },
];

export const lessonEntries = courses.flatMap((course) =>
  course.lessons.map((lesson) => ({ course, lesson }))
);

export const moduleCount = lessonEntries.filter(({ lesson }) => lesson.moduleId).length;

export const lessonHref = (courseId: string, lessonId: string) =>
  `/courses/${courseId}/${lessonId}`;

export const courseMinutes = (course: Course) =>
  course.lessons.reduce((total, lesson) => total + lesson.minutes, 0);

export function searchLessons(query: string) {
  const terms = query.trim().toLowerCase().replace(/_/g, " ").split(/\s+/).filter(Boolean);
  return lessonEntries.filter(({ course, lesson }) => {
    const text = [course.title, course.category, lesson.title, lesson.summary,
      lesson.moduleId?.replace(/_/g, " "), ...lesson.objectives, lesson.content].join(" ").toLowerCase();
    return terms.every((term) => text.includes(term));
  });
}
