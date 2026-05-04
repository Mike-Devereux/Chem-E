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

- [ ] Allow supervisors to access Django admin
- [ ] Allow supervisors to create and edit their own courses
- [ ] Allow supervisors to create and edit tutorials within their courses
- [ ] Allow supervisors to create and edit exercises within tutorials
- [ ] Allow supervisors to create and edit exercise variants within exercises

- [ ] Ensure the following fields are editable in admin:
  - [ ] exercise type (numerical / upload) (Exercise)
  - [ ] active/unlocked flag (Exercise)
  - [ ] reference solution (ExerciseVariant)
  - [ ] tolerance (ExerciseVariant)
  - [ ] available points (ExerciseVariant)

- [ ] Restrict supervisors to only see and edit their own content
- [ ] Improve admin usability:
  - [ ] inline editing (variants under exercises, etc.)
  - [ ] list display fields
  - [ ] filters and search

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