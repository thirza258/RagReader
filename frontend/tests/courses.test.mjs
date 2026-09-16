import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { courses, lessonEntries, lessonHref, searchLessons } from "../src/data/courses/index.ts";
import { parseCourseProgress, setLessonComplete, nextIncompleteLesson } from "../src/lib/courseProgress.ts";

const ids = lessonEntries.map(({ lesson }) => lesson.id);

test("every backend RAG module has exactly one dedicated lesson", () => {
  const backend = readFileSync(new URL("../../backend/common/analysis_modules.py", import.meta.url), "utf8");
  const catalog = backend.split("RAG_MODULE_IDS =")[0];
  const backendIds = [...catalog.matchAll(/"id": "([^"]+)"/g)].map((match) => match[1]).sort();
  const lessonModuleIds = lessonEntries.flatMap(({ lesson }) => lesson.moduleId ? [lesson.moduleId] : []).sort();
  assert.ok(backendIds.length > 0, "backend catalog must be readable");
  assert.deepEqual(lessonModuleIds, backendIds, "new backend modules need a lesson; no module may be duplicated");
});

test("course and lesson URLs are unambiguous and each quiz has a valid answer", () => {
  assert.equal(new Set(courses.map((course) => course.id)).size, courses.length);
  assert.equal(new Set(ids).size, ids.length, "lesson IDs are also browser progress keys");
  for (const { course, lesson } of lessonEntries) {
    assert.match(course.id, /^[a-z0-9]+(?:-[a-z0-9]+)*$/);
    assert.match(lesson.id, /^[a-z0-9]+(?:-[a-z0-9]+)*$/);
    assert.equal(lessonHref(course.id, lesson.id), `/courses/${course.id}/${lesson.id}`);
    assert.ok(lesson.quiz.options.length >= 2);
    assert.equal(new Set(lesson.quiz.options).size, lesson.quiz.options.length);
    assert.ok(Number.isInteger(lesson.quiz.answer) && lesson.quiz.answer >= 0 && lesson.quiz.answer < lesson.quiz.options.length);
    for (const source of lesson.sources || []) assert.equal(new URL(source.url).protocol, "https:");
  }
});

test("saved progress survives reload, repeated completion, and marking incomplete", () => {
  let progress = parseCourseProgress(null, ids);
  progress = setLessonComplete(progress, ids[0], true);
  progress = setLessonComplete(progress, ids[0], true);
  progress = setLessonComplete(progress, ids[2], true);
  const reloaded = parseCourseProgress(JSON.stringify(progress), ids);
  assert.deepEqual(reloaded.completed, [ids[0], ids[2]]);
  assert.equal(nextIncompleteLesson(ids, reloaded.completed), ids[1]);
  const reopened = setLessonComplete(reloaded, ids[0], false);
  assert.equal(nextIncompleteLesson(ids, reopened.completed), ids[0]);
  assert.deepEqual(reloaded.completed, [ids[0], ids[2]], "updates must not mutate prior state");
});

test("malformed, stale, and unknown storage entries cannot break or inflate progress", () => {
  for (const raw of ["{", "null", "true", "[]", '{"version":2,"completed":[]}', '{"version":1,"completed":"all"}']) {
    assert.deepEqual(parseCourseProgress(raw, ids), { version: 1, completed: [] });
  }
  const parsed = parseCourseProgress(JSON.stringify({ version: 1, completed: [ids[0], ids[0], "deleted-lesson", null, {}, 7] }), ids);
  assert.deepEqual(parsed.completed, [ids[0]]);
});

test("continuation crosses course boundaries and recognizes a finished path", () => {
  const firstCourseIds = courses[0].lessons.map((lesson) => lesson.id);
  assert.equal(nextIncompleteLesson(ids, firstCourseIds), courses[1].lessons[0].id);
  assert.equal(nextIncompleteLesson(ids, ids), undefined);
  assert.equal(nextIncompleteLesson([], []), undefined);
});

test("search handles module identifiers, mixed case, multiple words, and empty results", () => {
  assert.ok(searchLessons("  HyDE  ").some(({ lesson }) => lesson.moduleId === "hyde"));
  assert.ok(searchLessons("rewrite_retrieve_read").some(({ lesson }) => lesson.moduleId === "rewrite_retrieve_read"));
  assert.ok(searchLessons("cosine similarity").some(({ lesson }) => lesson.id === "embeddings-and-dense-search"));
  assert.equal(searchLessons(" ").length, lessonEntries.length);
  assert.deepEqual(searchLessons("zz-no-such-course-zz"), []);
});
