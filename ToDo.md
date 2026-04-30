# TODO.md

## Phase 0 — Project setup

* [ ] Create Django project
* [ ] Create main app (e.g. `core` or `elearning`)
* [ ] Configure SQLite database
* [ ] Configure media file storage (for uploads)
* [ ] Set up basic project structure (settings split optional)
* [ ] Create Git repository

---

## Phase 1 — Users & authentication

* [ ] Use Django built-in User model or extend it
* [ ] Add roles: student, supervisor, administrator
* [ ] Enforce email domain restriction (`@unibas.ch`, `@stud.unibas.ch`)
* [ ] Implement registration form
* [ ] Implement login/logout
* [ ] Implement password reset via email
* [ ] Restrict access to pages based on role

---

## Phase 2 — Core data models

* [ ] Create Course model
* [ ] Create Tutorial model
* [ ] Create Exercise model
* [ ] Create ExerciseVariant model
* [ ] Create Result (submission) model
* [ ] Add relationships between models
* [ ] Register all models in Django admin

---

## Phase 3 — Basic supervisor functionality (admin-first)

(Start with Django admin before building custom UI)

* [ ] Allow supervisors to create courses in admin
* [ ] Allow supervisors to create tutorials
* [ ] Allow supervisors to create exercises
* [ ] Allow supervisors to add exercise variants
* [ ] Add fields:

  * [ ] exercise type (numerical / upload)
  * [ ] tolerance
  * [ ] points
  * [ ] active/locked flag

---

## Phase 4 — Student-facing basics

* [ ] Create course list page
* [ ] Create course detail page (list tutorials)
* [ ] Create tutorial page (list exercises)
* [ ] Only show active/unlocked exercises
* [ ] Create exercise detail page

---

## Phase 5 — Numerical exercises

* [ ] Assign random variant per student (store it!)
* [ ] Create submission form (numerical input)
* [ ] Implement answer checking with tolerance
* [ ] Store result (score, correctness, timestamp)
* [ ] Show result to student after submission

---

## Phase 6 — File upload exercises

* [ ] Add file upload field to submission
* [ ] Restrict file types and size
* [ ] Store files securely (MEDIA_ROOT)
* [ ] Link file to Result model
* [ ] Allow student to upload/replace file

---

## Phase 7 — Supervisor grading & review

* [ ] View submissions per exercise
* [ ] Download uploaded files
* [ ] Add manual grading interface
* [ ] Store score + feedback
* [ ] Mark submission as graded

---

## Phase 8 — Results overview

* [ ] Create course summary page
* [ ] Show:

  * [ ] students
  * [ ] exercises
  * [ ] scores per exercise
* [ ] Highlight missing submissions
* [ ] Filter by tutorial / student

---

## Phase 9 — Archiving

* [ ] Add archive flag or archive table
* [ ] Implement “archive results” action
* [ ] Hide archived results from main view
* [ ] Create archive browsing page

---

## Phase 10 — Admin features

* [ ] Admin user list view
* [ ] Promote/demote users (student ↔ supervisor ↔ admin)
* [ ] Reset user passwords
* [ ] Allow admin to edit/delete any course/tutorial/exercise

---

## Phase 11 — Hardening & cleanup

* [ ] Permissions testing (students cannot access others’ data)
* [ ] Validate all inputs
* [ ] Improve error handling
* [ ] Add basic UI styling
* [ ] Add logging

---

## Phase 12 — Deployment prep

* [ ] Switch to PostgreSQL (optional at this stage)
* [ ] Configure static/media handling
* [ ] Prepare for Nginx + Gunicorn
* [ ] Backup strategy for DB and uploads