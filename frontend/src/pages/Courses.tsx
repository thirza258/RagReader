import { useEffect } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import { courses } from "../data/courses";
import { useCourseProgress } from "../hooks/useCourseProgress";
import CourseCatalog from "../components/courses/CourseCatalog";
import CourseOverview from "../components/courses/CourseOverview";
import LessonReader from "../components/courses/LessonReader";
import SEO from "../components/SEO";
import "../courses.css";

export default function Courses() {
  const params = useParams();
  const { pathname, hash } = useLocation();
  const { progress, storageAvailable, markComplete } = useCourseProgress();
  const course = courses.find((item) => item.id === params.courseId);
  const lesson = course?.lessons.find((item) => item.id === params.lessonId);
  const notFound = Boolean(params["*"] || (params.courseId && !course) || (params.lessonId && !lesson));

  useEffect(() => {
    if (hash) {
      document.getElementById(hash.slice(1))?.scrollIntoView();
    } else {
      window.scrollTo(0, 0);
      document.getElementById("course-page-title")?.focus({ preventScroll: true });
    }
  }, [pathname, hash]);

  return (
    <main className="courses-page container mx-auto min-h-screen max-w-6xl px-5 pb-20 pt-28 sm:px-8">
      {notFound ? (
        <div className="py-16">
          <SEO title="Lesson not found — RAGReader Courses" description="Find a course on RAG fundamentals, retrieval modules, or evaluation." canonicalUrl="https://rag.nevatal.tech/courses" />
          <p className="text-xs uppercase tracking-wide text-primary">Courses</p>
          <h1 id="course-page-title" tabIndex={-1} className="mt-3 text-4xl font-semibold">This lesson could not be found.</h1>
          <p className="mt-4 text-muted-foreground">Choose a lesson from the curriculum to continue learning.</p>
          <Link to="/courses" className="link mt-6 inline-block">Browse all courses</Link>
        </div>
      ) : course && lesson ? (
        <LessonReader key={lesson.id} course={course} lesson={lesson} completed={progress.completed} storageAvailable={storageAvailable} markComplete={markComplete} />
      ) : course ? (
        <CourseOverview course={course} completed={progress.completed} />
      ) : (
        <CourseCatalog progress={progress} storageAvailable={storageAvailable} />
      )}
    </main>
  );
}
