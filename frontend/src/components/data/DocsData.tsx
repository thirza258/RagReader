import { DocStep } from "../../types/types";

import landingPageImage from "../../assets/docs/docs_landingpage.png";
import loginImage from "../../assets/docs/docs_login.png";
import pdfInputImage from "../../assets/docs/docs_pdfinput.png";
import initImage from "../../assets/docs/docs_init.png";
import chatInterfaceImage from "../../assets/docs/docs_chat.png";
import triggerDeepImage from "../../assets/docs/docs_triggerdeep.png";
import groundTruthImage from "../../assets/docs/docs_groundtruth.png";
import sidebarImage from "../../assets/docs/docs_sidebar.png";
import deepAnalysisImage from "../../assets/docs/docs_deepanalysis.png";
import coursesImage from "../../assets/docs/docs_courses.png";

export const steps: DocStep[] = [
  {
    id: 1,
    title: "Explore the Benchmark & Landing Page",
    description:
      "Start on the homepage to explore multi-pipeline retrieval comparisons across Dense, Sparse, and Hybrid models, or jump straight into document analysis.",
    imagePath: landingPageImage,
    imageAlt: "RAGReader Landing Page and Benchmark Overview",
    imagePlaceholderText: "Landing Page Overview",
  },
  {
    id: 2,
    title: "Account Creation & Login",
    description:
      "Create a username and email. This unified login allows you to resume sessions and history seamlessly across devices.",
    imagePath: loginImage,
    imageAlt: "Login Screen Interface",
    imagePlaceholderText: "Login Image",
  },
  {
    id: 3,
    title: "Document Ingestion",
    description:
      "Upload PDF, Word, text or Markdown files, add a web page URL, or paste raw text. Each source becomes a document in your workspace library.",
    imagePath: pdfInputImage,
    imageAlt: "Document Upload Interface",
    imagePlaceholderText: "Document Upload Image",
  },
  {
    id: 4,
    title: "Background Ingestion & Vector Indexing",
    description:
      "Documents are processed in the background. The workspace library shows each step as it happens — text extracted, content cleaned, chunks created, embeddings generated, index built — and failed steps can be retried.",
    imagePath: initImage,
    imageAlt: "Document Vectorization and Initialization State",
    imagePlaceholderText: "Loading State",
  },
  {
    id: 5,
    title: "Workspace Chat with Citations",
    description: (
      <>
        Ask questions in a workspace conversation. Answers stream in, grounded with{" "}
        <em>dense retrieval</em>, and every claim carries a numbered citation — click one to
        open the passage, highlighted, in the reader. Conversations are saved, so you can
        come back to them later.
      </>
    ),
    imagePath: chatInterfaceImage,
    imageAlt: "Workspace chat with cited answers",
    imagePlaceholderText: "Workspace Chat",
  },
  {
    id: 6,
    title: "Trigger Deep Analysis",
    description:
      "Click the 'Deep analysis' button below an answer about a single document to benchmark multiple pipelines against that document.",
    imagePath: triggerDeepImage,
    imageAlt: "Deep Analysis Action Button under Chat Response",
    imagePlaceholderText: "Deep Analysis Button",
  },
  {
    id: 7,
    title: "Ground Truth Selection & Expected Response",
    description:
      "In the Ground Truth view, choose between manual chunk selection or candidate pooling (RRF), and provide your expected answer to measure retrieval precision.",
    imagePath: groundTruthImage,
    imageAlt: "Ground Truth Selection and Candidate Pooling UI",
    imagePlaceholderText: "Ground Truth UI",
  },
  {
    id: 8,
    title: "Sidebar Configuration",
    description:
      "Use the sidebar to configure advanced settings: select retrieval pipelines (Dense, Sparse BM25, Hybrid), choose language models, and tune top-K chunk limits.",
    imagePath: sidebarImage,
    imageAlt: "Deep Analysis Configuration Sidebar",
    imagePlaceholderText: "Sidebar Configuration",
  },
  {
    id: 9,
    title: "Multi-Pipeline Evaluation & Scoring",
    description:
      "Receive detailed relevance scores, precision, faithfulness, and answer relevance across all tested retrieval methods and LLMs simultaneously.",
    imagePath: deepAnalysisImage,
    imageAlt: "Multi-Pipeline Benchmark Evaluation Results",
    imagePlaceholderText: "Evaluation Results",
  },
  {
    id: 10,
    title: "Interactive RAG Courses",
    description:
      "Deepen your understanding with structured RAG courses covering everything from vector basics to reranking, query routing, and automated evaluation metrics.",
    imagePath: coursesImage,
    imageAlt: "RAGReader Interactive Courses Catalog",
    imagePlaceholderText: "Courses Catalog",
  },
];
