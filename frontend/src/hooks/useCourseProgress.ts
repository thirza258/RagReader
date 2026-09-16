import { useEffect, useState } from "react";
import { lessonEntries } from "../data/courses";
import { COURSE_PROGRESS_KEY, parseCourseProgress, setLessonComplete } from "../lib/courseProgress";

const validIds = lessonEntries.map(({ lesson }) => lesson.id);

function readProgress() {
  try {
    return { progress: parseCourseProgress(localStorage.getItem(COURSE_PROGRESS_KEY), validIds), storageAvailable: true };
  } catch {
    return { progress: parseCourseProgress(null, validIds), storageAvailable: false };
  }
}

export function useCourseProgress() {
  const [state, setState] = useState(readProgress);

  useEffect(() => {
    const onStorage = (event: StorageEvent) => {
      if (event.key === COURSE_PROGRESS_KEY || event.key === null) setState(readProgress());
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  function markComplete(lessonId: string, complete: boolean) {
    if (!validIds.includes(lessonId)) return;
    const progress = setLessonComplete(state.progress, lessonId, complete);
    let storageAvailable = true;
    try {
      localStorage.setItem(COURSE_PROGRESS_KEY, JSON.stringify(progress));
    } catch {
      storageAvailable = false;
    }
    setState({ progress, storageAvailable });
  }

  return { ...state, markComplete };
}
