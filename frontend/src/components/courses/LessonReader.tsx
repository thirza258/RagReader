import { useState } from "react";
import { Link } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import { ArrowLeft, ArrowRight, CheckCircle2, ExternalLink } from "lucide-react";
import type { Course, Lesson } from "../../data/courses/types";
import { lessonEntries, lessonHref } from "../../data/courses";
import { Button } from "../ui/button";
import SEO from "../SEO";

interface ReaderProps {
  course: Course;
  lesson: Lesson;
  completed: string[];
  storageAvailable: boolean;
  markComplete: (id: string, complete: boolean) => void;
}

function LessonNavigation({ course, lesson, completed }: Pick<ReaderProps, "course" | "lesson" | "completed">) {
  return (
    <nav aria-label={`Lessons in ${course.title}`}>
      <ol className="space-y-1">
        {course.lessons.map((item, index) => (
          <li key={item.id}><Link to={lessonHref(course.id, item.id)} aria-current={item.id === lesson.id ? "page" : undefined}
            className={`flex items-start gap-3 border-l-2 px-3 py-3 text-sm ${item.id === lesson.id ? "border-primary bg-primary/5 text-primary" : "border-transparent text-muted-foreground hover:bg-muted hover:text-foreground"}`}>
            {completed.includes(item.id) ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" aria-label="Completed" /> : <span className="mt-0.5 font-mono text-xs" aria-hidden="true">{String(index + 1).padStart(2, "0")}</span>}
            <span>{item.title}</span>
          </Link></li>
        ))}
      </ol>
    </nav>
  );
}

export default function LessonReader({ course, lesson, completed, storageAvailable, markComplete }: ReaderProps) {
  const [selected, setSelected] = useState<number | null>(null);
  const [submitted, setSubmitted] = useState(false);
  const complete = completed.includes(lesson.id);
  const passed = submitted && selected === lesson.quiz.answer;
  const position = lessonEntries.findIndex((entry) => entry.lesson.id === lesson.id);
  const previous = lessonEntries[position - 1];
  const next = lessonEntries[position + 1];
  const coursePosition = course.lessons.indexOf(lesson);
  const count = course.lessons.filter((item) => completed.includes(item.id)).length;
  return (
    <>
      <SEO title={`${lesson.title} — RAGReader Courses`} description={lesson.summary} canonicalUrl={`https://rag.nevatal.tech${lessonHref(course.id, lesson.id)}`} ogType="article" />
      <nav aria-label="Breadcrumb" className="mb-8 flex flex-wrap items-center gap-2 text-sm text-muted-foreground"><Link to="/courses" className="link">Courses</Link><span aria-hidden="true">/</span><Link to={`/courses/${course.id}`} className="link">{course.title}</Link><span aria-hidden="true">/</span><span>Lesson {coursePosition + 1}</span></nav>
      <div className="grid items-start gap-8 lg:grid-cols-[15rem_minmax(0,1fr)] lg:gap-12">
        <aside className="hidden lg:sticky lg:top-24 lg:block">
          <Link to={`/courses/${course.id}`} className="font-serif text-lg font-semibold hover:text-primary">{course.title}</Link>
          <p className="mb-3 mt-2 text-xs text-muted-foreground">{count} / {course.lessons.length} complete</p>
          <progress className="course-progress mb-5 w-full" value={count} max={course.lessons.length} aria-label={`${course.title} completion`} />
          <LessonNavigation course={course} lesson={lesson} completed={completed} />
          <Link to="/courses" className="link mt-6 inline-flex items-center gap-2 text-sm"><ArrowLeft className="h-4 w-4" aria-hidden="true" />All courses</Link>
        </aside>
        <div className="min-w-0 max-w-3xl">
          <details className="mb-6 border border-border p-4 lg:hidden"><summary className="cursor-pointer text-sm font-medium">Course contents · {count}/{course.lessons.length} complete</summary><div className="mt-3"><LessonNavigation course={course} lesson={lesson} completed={completed} /></div></details>
          <article>
            <header className="border-b border-border pb-7">
              <div className="flex flex-wrap items-center gap-3 text-xs uppercase tracking-wide text-muted-foreground"><span className="text-primary">Lesson {String(coursePosition + 1).padStart(2, "0")}</span><span>{lesson.minutes} min with practice</span>{lesson.moduleId && <span className="border border-border px-2 py-1">RAG module</span>}{complete && <span className="inline-flex items-center gap-1 text-primary"><CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />Complete</span>}</div>
              <h1 id="course-page-title" tabIndex={-1} className="mt-4 text-3xl font-semibold leading-tight sm:text-4xl">{lesson.title}</h1>
              <p className="prose-note mt-4">{lesson.summary}</p>
            </header>
            <section className="my-7 border-l-2 border-primary bg-muted/50 px-5 py-4" aria-labelledby="lesson-objectives-heading">
              <h2 id="lesson-objectives-heading" className="font-sans text-xs font-semibold uppercase tracking-wide">After this lesson, you can</h2>
              <ul className="mt-3 list-disc space-y-2 pl-5 text-sm leading-relaxed">{lesson.objectives.map((objective) => <li key={objective}>{objective}</li>)}</ul>
            </section>
            <div className="course-prose"><ReactMarkdown>{lesson.content}</ReactMarkdown></div>
            {lesson.sources && (
              <section className="mt-8 border-t border-border pt-5" aria-labelledby="lesson-sources-heading"><h2 id="lesson-sources-heading" className="text-lg font-semibold">Primary sources & further reading</h2><ul className="mt-3 space-y-2 text-sm">{lesson.sources.map((source) => <li key={source.url}><a href={source.url} target="_blank" rel="noreferrer" className="link inline-flex items-start gap-2">{source.title}<ExternalLink className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" /><span className="sr-only"> (opens in a new tab)</span></a></li>)}</ul></section>
            )}
          </article>

          <section className="mt-10 border border-border p-5 sm:p-6" aria-labelledby="lesson-exercise-heading">
            <p className="text-xs font-medium uppercase tracking-wide text-primary">Put it into practice</p>
            <h2 id="lesson-exercise-heading" className="mt-2 text-2xl font-semibold">{lesson.exercise.title}</h2>
            <ol className="mt-5 list-decimal space-y-3 pl-5 text-sm leading-relaxed">{lesson.exercise.steps.map((step) => <li key={step}>{step}</li>)}</ol>
            <details className="mt-5 border-t border-border pt-4"><summary className="cursor-pointer text-sm font-medium text-primary">Show a suggested solution</summary><p className="mt-3 text-sm leading-relaxed text-muted-foreground">{lesson.exercise.solution}</p></details>
            <div className="mt-5 flex flex-wrap gap-x-5 gap-y-2 text-xs"><a href="/course-materials/northstar-handbook.txt" download className="link">Practice handbook</a><a href="/course-materials/experiment-worksheet.md" download className="link">Experiment worksheet</a><Link to="/docs" className="link">App walkthrough</Link></div>
          </section>

          <section className="mt-8 border border-border bg-muted/40 p-5 sm:p-6" aria-labelledby="lesson-quiz-heading">
            <h2 id="lesson-quiz-heading" className="text-2xl font-semibold">Check your understanding</h2>
            <form className="mt-4" onSubmit={(event) => { event.preventDefault(); if (selected !== null) setSubmitted(true); }}>
              <fieldset>
                <legend className="mb-4 text-sm font-medium leading-relaxed">{lesson.quiz.question}</legend>
                <div className="space-y-2">{lesson.quiz.options.map((option, index) => <label key={option} className={`flex cursor-pointer items-start gap-3 border bg-background p-3 text-sm leading-relaxed ${selected === index ? "border-primary" : "border-border hover:border-input"}`}><input type="radio" name="lesson-answer" value={index} checked={selected === index} onChange={() => { setSelected(index); setSubmitted(false); }} className="mt-1 h-4 w-4 shrink-0 accent-primary" /><span>{option}</span></label>)}</div>
              </fieldset>
              <Button type="submit" variant="outline" className="mt-4" disabled={selected === null}>Check answer</Button>
              <div aria-live="polite" aria-atomic="true">{submitted && <div className="mt-4 border-t border-border pt-4 text-sm leading-relaxed"><p className={passed ? "font-medium text-status-success" : "font-medium text-destructive"}>{passed ? "Correct. You are ready to complete this lesson." : "Not quite. Review the explanation and try again."}</p><p className="mt-2 text-muted-foreground">{lesson.quiz.explanation}</p></div>}</div>
            </form>
          </section>

          <div className="mt-8 border-y border-border py-5">
            <div className="flex flex-wrap items-center gap-4">
              {complete ? <><p className="flex items-center gap-2 text-sm font-medium text-primary" role="status"><CheckCircle2 className="h-5 w-5" aria-hidden="true" />Lesson complete</p><button type="button" onClick={() => markComplete(lesson.id, false)} className="text-xs text-muted-foreground underline underline-offset-4">Mark incomplete</button></> : <Button disabled={!passed} onClick={() => markComplete(lesson.id, true)}><CheckCircle2 aria-hidden="true" />Mark lesson complete</Button>}
              {!passed && !complete && <p className="text-xs text-muted-foreground">Answer the knowledge check correctly to mark complete.</p>}
            </div>
            <p className="mt-3 text-xs text-muted-foreground">{storageAvailable ? "Progress is saved in this browser. Exercises are self-guided." : "Browser storage is unavailable. Progress will last for this visit."}</p>
          </div>
          <nav aria-label="Lesson pagination" className="mt-6 grid gap-4 sm:grid-cols-2">
            {previous ? <Link to={lessonHref(previous.course.id, previous.lesson.id)} className="group border border-border p-4 hover:border-primary"><span className="flex items-center gap-2 text-xs text-muted-foreground"><ArrowLeft className="h-3.5 w-3.5" aria-hidden="true" />Previous lesson</span><span className="mt-2 block font-serif text-base group-hover:text-primary">{previous.lesson.title}</span></Link> : <Link to={`/courses/${course.id}`} className="link flex items-center gap-2 text-sm"><ArrowLeft className="h-4 w-4" aria-hidden="true" />Course overview</Link>}
            {next ? <Link to={lessonHref(next.course.id, next.lesson.id)} className="group border border-border p-4 hover:border-primary"><span className="flex items-center gap-2 text-xs text-muted-foreground">{next.course.id !== course.id ? "Next course" : "Next lesson"}<ArrowRight className="h-3.5 w-3.5" aria-hidden="true" /></span><span className="mt-2 block font-serif text-base group-hover:text-primary">{next.lesson.title}</span></Link> : <Link to="/courses" className="link flex items-center justify-end gap-2 text-sm">Return to your learning path<ArrowRight className="h-4 w-4" aria-hidden="true" /></Link>}
          </nav>
        </div>
      </div>
    </>
  );
}
