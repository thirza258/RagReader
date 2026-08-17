import React, { useEffect } from "react";

interface SEOProps {
  title?: string;
  description?: string;
  keywords?: string[];
  canonicalUrl?: string;
  ogType?: string;
  ogImage?: string;
  jsonLd?: Record<string, any> | Record<string, any>[];
}

const DEFAULT_TITLE = "RAGReader — Compare Dense, Sparse & Hybrid RAG Pipelines";
const DEFAULT_DESCRIPTION =
  "Ask questions about your own PDF, URL, or pasted text, then score the answer across 9 RAG pipelines — Dense, Sparse and Hybrid retrieval x three LLMs.";
const DEFAULT_CANONICAL = "https://rag.nevatal.tech/";
const DEFAULT_OG_IMAGE = "https://rag.nevatal.tech/og-image.jpg";
const DEFAULT_KEYWORDS = [
  "RAG pipeline comparison",
  "Dense retrieval",
  "Sparse retrieval BM25",
  "Hybrid retrieval reranking",
  "RAG evaluation metrics",
  "Precision@K",
  "Recall@K",
  "ROUGE-L",
  "Reciprocal Rank Fusion",
  "LLM evaluation benchmark",
  "OpenRouter RAG",
];

export const SEO: React.FC<SEOProps> = ({
  title = DEFAULT_TITLE,
  description = DEFAULT_DESCRIPTION,
  keywords = DEFAULT_KEYWORDS,
  canonicalUrl = DEFAULT_CANONICAL,
  ogType = "website",
  ogImage = DEFAULT_OG_IMAGE,
  jsonLd,
}) => {
  useEffect(() => {
    // 1. Update Title
    document.title = title;

    // Helper function to update or create meta tags
    const updateMetaTag = (selector: string, attribute: string, value: string) => {
      let element = document.querySelector(selector) as HTMLMetaElement | null;
      if (!element) {
        element = document.createElement("meta");
        const match = selector.match(/\[(name|property)="(.*?)"\]/);
        if (match) {
          element.setAttribute(match[1], match[2]);
        }
        document.head.appendChild(element);
      }
      element.setAttribute(attribute, value);
    };

    // Helper function for link tags
    const updateLinkTag = (rel: string, href: string) => {
      let element = document.querySelector(`link[rel="${rel}"]`) as HTMLLinkElement | null;
      if (!element) {
        element = document.createElement("link");
        element.setAttribute("rel", rel);
        document.head.appendChild(element);
      }
      element.setAttribute("href", href);
    };

    // 2. Update Standard Meta Tags
    updateMetaTag('meta[name="description"]', "content", description);
    updateMetaTag('meta[name="keywords"]', "content", keywords.join(", "));

    // 3. Update Canonical URL
    updateLinkTag("canonical", canonicalUrl);

    // 4. Update Open Graph Tags
    updateMetaTag('meta[property="og:title"]', "content", title);
    updateMetaTag('meta[property="og:description"]', "content", description);
    updateMetaTag('meta[property="og:url"]', "content", canonicalUrl);
    updateMetaTag('meta[property="og:type"]', "content", ogType);
    updateMetaTag('meta[property="og:image"]', "content", ogImage);

    // 5. Update Twitter Cards
    updateMetaTag('meta[name="twitter:title"]', "content", title);
    updateMetaTag('meta[name="twitter:description"]', "content", description);
    updateMetaTag('meta[name="twitter:image"]', "content", ogImage);

    // 6. Manage Dynamic JSON-LD Structured Data
    const JSON_LD_ID = "dynamic-json-ld";
    let scriptTag = document.getElementById(JSON_LD_ID) as HTMLScriptElement | null;

    if (jsonLd) {
      if (!scriptTag) {
        scriptTag = document.createElement("script");
        scriptTag.id = JSON_LD_ID;
        scriptTag.type = "application/ld+json";
        document.head.appendChild(scriptTag);
      }
      scriptTag.textContent = JSON.stringify(jsonLd);
    } else if (scriptTag) {
      scriptTag.remove();
    }
  }, [title, description, keywords, canonicalUrl, ogType, ogImage, jsonLd]);

  return null;
};

export default SEO;
