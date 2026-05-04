# TODO.md

## Phase 0 — Project setup

* [x] Create Git repository
* [x] Create Django project named `chem_e`
* [x] Configure SQLite database
* [x] Create main app named `core`
* [x] Configure media file storage (for uploads)
* [x] Set up basic project structure

---

## Phase 1 — Users & authentication

* [x] Use Django built-in User model or extend it
* [x] Add roles: student, supervisor, administrator
* [x] Enforce email domain restriction (`@unibas.ch`, `@stud.unibas.ch`)
* [x] Implement registration form
* [x] Implement login/logout
* [x] Implement password reset via email
* [x] Restrict access to pages based on role

---

## Phase 2 — Core data models

* [x] Create Course model
* [x] Create Tutorial model
* [x] Create Exercise model
* [x] Create ExerciseVariant model
* [x] Create Result (submission) model
* [x] Add relationships between models
* [x] Register all models in Django admin

---

## Phase 3 — Basic supervisor functionality (admin-first)

(Start with Django admin before building custom UI)

- [x] Allow supervisors to access Django admin
- [x] Allow supervisors to create and edit their own courses
- [x] Allow supervisors to create and edit tutorials within their courses
- [x] Allow supervisors to create and edit exercises within tutorials
- [x] Allow supervisors to create and edit exercise variants within exercises

- [x] Ensure the following fields are editable in admin:
  - [x] exercise type (numerical / upload) (Exercise)
  - [x] active/unlocked flag (Exercise)
  - [x] reference solution (ExerciseVariant)
  - [x] tolerance (ExerciseVariant)
  - [x] available points (ExerciseVariant)

- [x] Restrict supervisors to only see and edit their own content
- [x] Improve admin usability:
  - [x] inline editing (variants under exercises, etc.)
  - [x] list display fields
  - [x] filters and search

---

## Phase 4 — Student-facing basics

* [x] Create course list page
* [x] Create course detail page (list tutorials)
* [x] Create tutorial page (list exercises)
* [x] Only show active/unlocked exercises
* [x] Create exercise detail page

---

## Phase 4a — Development seed data

- [x] Add a Django management command to create demo data
- [x] Create one demo course
- [x] Create two demo tutorials
- [x] Create several demo exercises
- [x] Include both numerical and upload-type exercises
- [x] Include exercise variants with reference solutions, tolerance, and points
- [x] Ensure the command can be run repeatedly without duplicating data

---

## Phase 5 — Numerical exercises

* [x] Assign random variant per student (store it!)
* [x] Create submission form (numerical input)
* [x] Implement answer checking with tolerance
* [x] Store result (score, correctness, timestamp)
* [x] Show result to student after submission

---

## Phase 6 — File upload exercises

* [x] Add file upload field to submission
* [x] Restrict file types and size
* [x] Store files securely (MEDIA_ROOT)
* [x] Link file to Result model
* [x] Allow student to upload/replace file

---

## Phase 7 — Supervisor grading & review

* [x] View submissions per exercise
* [x] Download uploaded files
* [x] Add manual grading interface
* [x] Store score + feedback
* [x] Mark submission as graded

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