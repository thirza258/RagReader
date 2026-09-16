export const COURSE_PROGRESS_KEY = "ragreader:course-progress:v1";

export interface CourseProgress {
  version: 1;
  completed: string[];
}

export function parseCourseProgress(raw: string | null, validIds: readonly string[]): CourseProgress {
  const empty: CourseProgress = { version: 1, completed: [] };
  if (!raw) return empty;
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || !("version" in parsed) ||
        parsed.version !== 1 || !("completed" in parsed) || !Array.isArray(parsed.completed)) return empty;
    const valid = new Set(validIds);
    return {
      version: 1,
      completed: [...new Set(parsed.completed.filter((id): id is string =>
        typeof id === "string" && valid.has(id)))],
    };
  } catch {
    return empty;
  }
}

export function setLessonComplete(progress: CourseProgress, lessonId: string, complete: boolean): CourseProgress {
  const completed = new Set(progress.completed);
  if (complete) completed.add(lessonId);
  else completed.delete(lessonId);
  return { version: 1, completed: [...completed] };
}

export function nextIncompleteLesson(lessonIds: readonly string[], completed: readonly string[]) {
  const done = new Set(completed);
  return lessonIds.find((id) => !done.has(id));
}
