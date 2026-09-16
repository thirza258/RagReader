import { Link, useSearchParams } from "react-router-dom";
import { ArrowRight, CheckCircle2, Download, Search } from "lucide-react";
import { courses, courseMinutes, lessonEntries, lessonHref, moduleCount, searchLessons } from "../../data/courses";
import type { CourseProgress } from "../../lib/courseProgress";
import { nextIncompleteLesson } from "../../lib/courseProgress";
import { Button } from "../ui/button";
import SEO from "../SEO";
import PipelineExplorer from "./PipelineExplorer";

const categories = ["All courses", "Fundamentals", "RAG modules", "Evaluation", "Practice"];

export default function CourseCatalog({ progress, storageAvailable }: { progress: CourseProgress; storageAvailable: boolean }) {
  const [params, setParams] = useSearchParams();
  const query = params.get("q") || "";
  const category = categories.includes(params.get("category") || "") ? params.get("category")! : "All courses";
  const completed = new Set(progress.completed);
  const remainingId = nextIncompleteLesson(lessonEntries.map(({ lesson }) => lesson.id), progress.completed);
  const next = lessonEntries.find(({ lesson }) => lesson.id === remainingId) || lessonEntries[0];
  const finished = completed.size === lessonEntries.length;
  const totalMinutes = courses.reduce((sum, course) => sum + courseMinutes(course), 0);
  const results = searchLessons(query).filter(({ course, lesson }) =>
    category === "All courses" || (category === "RAG modules" ? Boolean(lesson.moduleId) : course.category === category));
  const visibleCourses = courses.filter((course) => results.some((entry) => entry.course.id === course.id));
  const filtering = Boolean(query.trim()) || category !== "All courses";

  function updateFilter(key: string, value: string) {
    const nextParams = new URLSearchParams(params);
    if (value && value !== "All courses") nextParams.set(key, value);
    else nextParams.delete(key);
    setParams(nextParams, { replace: true });
  }

  return (
    <>
      <SEO title="RAG Courses — Fundamentals to Advanced Modules | RAGReader" description="Learn RAG in six complete courses: 28 lessons, all 13 modules, worked examples, quizzes, hands-on exercises, and a final capstone." canonicalUrl="https://rag.nevatal.tech/courses" />
      <header className="grid gap-8 border-b border-border pb-10 lg:grid-cols-[1fr_18rem] lg:gap-16">
        <div>
          <p className="text-xs font-medium uppercase tracking-[0.18em] text-primary">The RAGReader classroom</p>
          <h1 id="course-page-title" tabIndex={-1} className="mt-4 text-4xl font-semibold leading-tight sm:text-5xl">A complete course in RAG.</h1>
          <p className="prose-note measure mt-5">Understand the fundamentals, explore every module, and learn to explain why an answer works. Follow the full learning path or open the topic you need.</p>
          <dl className="mt-7 flex flex-wrap gap-x-8 gap-y-4 text-sm">
            <div><dt className="font-mono text-xl text-foreground">{courses.length}</dt><dd className="mt-1 text-muted-foreground">Courses</dd></div>
            <div><dt className="font-mono text-xl text-foreground">{lessonEntries.length}</dt><dd className="mt-1 text-muted-foreground">Lessons & quizzes</dd></div>
            <div><dt className="font-mono text-xl text-foreground">{moduleCount}</dt><dd className="mt-1 text-muted-foreground">RAG modules</dd></div>
            <div><dt className="font-mono text-xl text-foreground">~{Math.round(totalMinutes / 60)}h</dt><dd className="mt-1 text-muted-foreground">Reading & practice</dd></div>
          </dl>
        </div>
        <aside aria-label="Learning progress" className="self-start border border-border bg-muted/40 p-5">
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Your learning path</p>
          <p className="mt-4 font-serif text-xl font-semibold">{finished ? "Learning path complete" : completed.size ? "Pick up where you left off" : "Start with the foundations"}</p>
          <p className="mt-2 text-sm text-muted-foreground" aria-live="polite">{completed.size} of {lessonEntries.length} lessons complete</p>
          <progress className="course-progress mt-4 w-full" value={completed.size} max={lessonEntries.length} aria-label="Overall course completion" />
          <Button asChild className="mt-5 w-full"><Link to={lessonHref(next.course.id, next.lesson.id)}>{finished ? "Review the fundamentals" : completed.size ? "Continue learning" : "Start learning"}<ArrowRight aria-hidden="true" /></Link></Button>
          <p className="mt-3 text-xs leading-relaxed text-muted-foreground">{storageAvailable ? "Free to read, no sign-in needed. Progress is saved in this browser, not synced to an account." : "Browser storage is unavailable. Progress will remain available during this visit."}</p>
        </aside>
      </header>

      <PipelineExplorer />

      <section aria-labelledby="curriculum-heading">
        <div className="flex flex-col justify-between gap-5 sm:flex-row sm:items-end">
          <div><p className="text-xs uppercase tracking-wide text-primary">The full curriculum</p><h2 id="curriculum-heading" className="mt-2 text-3xl font-semibold">From first principles to practice</h2></div>
          <div className="relative sm:w-72">
            <label htmlFor="course-search" className="sr-only">Search courses and lessons</label>
            <Search className="pointer-events-none absolute left-3 top-3 h-4 w-4 text-muted-foreground" aria-hidden="true" />
            <input id="course-search" type="search" value={query} onChange={(event) => updateFilter("q", event.target.value)} placeholder="Search courses and lessons" className="h-10 w-full border border-input bg-background pl-9 pr-3 text-sm" />
          </div>
        </div>
        <div role="group" aria-label="Filter courses by topic" className="my-6 flex flex-wrap gap-2">
          {categories.map((item) => <button key={item} type="button" aria-pressed={category === item} onClick={() => updateFilter("category", item)} className={`border px-3 py-2 text-sm ${category === item ? "border-primary bg-primary text-primary-foreground" : "border-border text-muted-foreground hover:bg-muted"}`}>{item}</button>)}
        </div>
        {filtering && <p className="mb-5 text-sm text-muted-foreground" role="status">{results.length} matching {results.length === 1 ? "lesson" : "lessons"} in {visibleCourses.length} {visibleCourses.length === 1 ? "course" : "courses"}</p>}
        {visibleCourses.length ? (
          <div className="grid gap-5 md:grid-cols-2">
            {visibleCourses.map((course) => {
              const done = course.lessons.filter((lesson) => completed.has(lesson.id)).length;
              const shownLessons = results.filter((entry) => entry.course.id === course.id);
              return (
                <article key={course.id} className="flex flex-col border border-border p-5 sm:p-6">
                  <div className="flex items-center justify-between gap-3 text-xs"><span className="font-mono text-primary">COURSE {String(courses.indexOf(course) + 1).padStart(2, "0")}</span><span className="text-muted-foreground">{course.level} · {courseMinutes(course)} min</span></div>
                  <h3 className="mt-4 text-2xl font-semibold"><Link to={`/courses/${course.id}`} className="hover:text-primary">{course.title}</Link></h3>
                  <p className="mt-3 text-sm leading-relaxed text-muted-foreground">{course.description}</p>
                  <ul className="my-5 space-y-2 border-t border-border pt-4 text-sm">
                    {(filtering ? shownLessons : shownLessons.slice(0, 3)).map(({ lesson }) => <li key={lesson.id}><Link to={lessonHref(course.id, lesson.id)} className="flex items-start gap-2 hover:text-primary">{completed.has(lesson.id) ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-primary" aria-label="Completed" /> : <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-border" aria-hidden="true" />}<span>{lesson.title}</span></Link></li>)}
                    {!filtering && course.lessons.length > 3 && <li className="pl-3.5 text-xs text-muted-foreground">+ {course.lessons.length - 3} more lessons</li>}
                  </ul>
                  <div className="mt-auto flex items-center justify-between gap-3 border-t border-border pt-4 text-sm"><span className="text-muted-foreground">{done} / {course.lessons.length} complete</span><Link to={`/courses/${course.id}`} className="link inline-flex items-center gap-2">View course<ArrowRight className="h-4 w-4" aria-hidden="true" /></Link></div>
                </article>
              );
            })}
          </div>
        ) : (
          <div className="border border-dashed border-border p-10 text-center"><h3 className="text-xl font-semibold">No matching lessons</h3><p className="mt-2 text-sm text-muted-foreground">Try a topic such as embeddings, HyDE, or evaluation.</p><Button variant="outline" className="mt-4" onClick={() => setParams({}, { replace: true })}>Clear filters</Button></div>
        )}
      </section>

      <section className="mt-12 grid gap-6 border-y border-border py-8 sm:grid-cols-2" aria-labelledby="course-materials-heading">
        <div><h2 id="course-materials-heading" className="text-2xl font-semibold">A small document. Real experiments.</h2><p className="prose-note mt-3 text-base">Practice on a fictional handbook with rules, exceptions, and missing facts. Every lesson includes a worked example, an exercise with a suggested solution, and a knowledge check.</p></div>
        <div className="space-y-3 text-sm">
          <a href="/course-materials/northstar-handbook.txt" download className="link flex items-center gap-2"><Download className="h-4 w-4" aria-hidden="true" />Download the practice handbook (.txt)</a>
          <a href="/course-materials/experiment-worksheet.md" download className="link flex items-center gap-2"><Download className="h-4 w-4" aria-hidden="true" />Download the experiment worksheet (.md)</a>
          <p className="pt-2 leading-relaxed text-muted-foreground">Written exercises work on their own. Running analyses uses your configured RAGReader backend and model services.</p>
          <Link to="/docs" className="link inline-block">Open the application walkthrough</Link>
        </div>
      </section>
    </>
  );
}
