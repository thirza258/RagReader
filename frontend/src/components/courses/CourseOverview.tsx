import { Link } from "react-router-dom";
import { ArrowLeft, ArrowRight, CheckCircle2, Clock } from "lucide-react";
import type { Course } from "../../data/courses/types";
import { courseMinutes, courses, lessonHref } from "../../data/courses";
import { nextIncompleteLesson } from "../../lib/courseProgress";
import { Button } from "../ui/button";
import SEO from "../SEO";

export default function CourseOverview({ course, completed }: { course: Course; completed: string[] }) {
  const done = new Set(completed);
  const count = course.lessons.filter((lesson) => done.has(lesson.id)).length;
  const nextId = nextIncompleteLesson(course.lessons.map((lesson) => lesson.id), completed) || course.lessons[0].id;
  return (
    <>
      <SEO title={`${course.title} — RAGReader Courses`} description={course.description} canonicalUrl={`https://rag.nevatal.tech/courses/${course.id}`} />
      <Link to="/courses" className="link inline-flex items-center gap-2 text-sm"><ArrowLeft className="h-4 w-4" aria-hidden="true" />All courses</Link>
      <header className="mt-8 grid gap-8 border-b border-border pb-10 lg:grid-cols-[1fr_18rem] lg:gap-16">
        <div>
          <p className="font-mono text-xs uppercase tracking-wide text-primary">Course {String(courses.indexOf(course) + 1).padStart(2, "0")} · {course.level}</p>
          <h1 id="course-page-title" tabIndex={-1} className="mt-4 text-4xl font-semibold sm:text-5xl">{course.title}</h1>
          <p className="prose-note measure mt-5">{course.description}</p>
          <p className="mt-5 flex items-center gap-2 text-sm text-muted-foreground"><Clock className="h-4 w-4" aria-hidden="true" />{course.lessons.length} lessons · About {courseMinutes(course)} minutes with practice</p>
          <Button asChild className="mt-6"><Link to={lessonHref(course.id, nextId)}>{count === course.lessons.length ? "Review course" : count ? "Continue course" : "Start course"}<ArrowRight aria-hidden="true" /></Link></Button>
        </div>
        <aside className="border border-border bg-muted/40 p-5">
          <h2 className="text-lg font-semibold">What you will learn</h2>
          <ul className="mt-4 space-y-3 text-sm leading-relaxed">{course.outcomes.map((outcome) => <li key={outcome} className="flex gap-2"><span className="text-primary" aria-hidden="true">→</span>{outcome}</li>)}</ul>
          <p className="mt-5 border-t border-border pt-4 text-xs leading-relaxed text-muted-foreground"><strong className="font-medium text-foreground">Before you begin: </strong>{course.prerequisites}</p>
        </aside>
      </header>
      <section className="mt-8" aria-labelledby="course-syllabus-heading">
        <div className="mb-5 flex flex-wrap items-baseline justify-between gap-2"><h2 id="course-syllabus-heading" className="text-2xl font-semibold">Your syllabus</h2><p className="text-sm text-muted-foreground">{count} of {course.lessons.length} complete</p></div>
        <progress className="course-progress mb-4 w-full" value={count} max={course.lessons.length} aria-label={`${course.title} completion`} />
        <ol className="border-t border-border">
          {course.lessons.map((lesson, index) => (
            <li key={lesson.id} className="border-b border-border">
              <Link to={lessonHref(course.id, lesson.id)} className="group flex items-start gap-4 py-6 sm:gap-6">
                <span className="mt-1 w-6 shrink-0 font-mono text-sm text-primary">{done.has(lesson.id) ? <CheckCircle2 className="h-5 w-5" aria-label="Completed" /> : String(index + 1).padStart(2, "0")}</span>
                <div className="min-w-0 flex-1"><h3 className="text-xl font-semibold group-hover:text-primary">{lesson.title}</h3><p className="mt-2 text-sm leading-relaxed text-muted-foreground">{lesson.summary}</p><p className="mt-2 text-xs text-muted-foreground">{lesson.minutes} min · Exercise & knowledge check{lesson.moduleId ? " · RAG module" : ""}</p></div>
                <ArrowRight className="mt-1 h-5 w-5 shrink-0 text-muted-foreground group-hover:text-primary" aria-hidden="true" />
              </Link>
            </li>
          ))}
        </ol>
      </section>
      <p className="mt-8 text-sm text-muted-foreground">You can study lessons in any order. Completion is saved in this browser. <Link to="/courses#course-materials-heading" className="link">Get the practice materials.</Link></p>
    </>
  );
}
