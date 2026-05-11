# SPEC.md — University E-Learning Exercise Tool

## 1. Project overview

This project is a web-based e-learning tool for university courses. It allows students to complete course exercises online and allows supervisors to create, manage, assess, archive, and review exercises and student submissions.

The tool is intended to run on an Ubuntu Linux server with a local web server, hosted behind a university firewall.

## 2. Core user roles

### 2.1 Student

Students can:

* create an account using a university e-mail address;
* log in securely;
* view available courses;
* select a course;
* view available tutorials/sessions within that course;
* view exercises that are currently active that belong to that tutorial;
* complete or modify exercises by either:

  * entering a numerical answer; or
  * uploading a document;
* view a personal summary of completed exercises and corresponding scores.

### 2.2 Supervisor

Supervisors can:

* log in securely;
* create and manage courses;
* create and manage tutorials/sessions within courses;
* create and manage exercises within tutorials;
* enter exercise text;
* upload images for exercises;
* define the required solution input type for each exercise;
* define numerical reference solutions;
* review student document uploads;
* manually enter results for exercises requiring uploaded files;
* view course-level summary pages showing exercise results per student;
* delete results;
* archive results;
* browse archived results later;
* deactivate or activate exercises to control student access.

Administrators can:

* Create and delete admin and supervisor accounts using university e-mail addresses;
* Set and reset admin, supervisor or user passwords

## 3. Authentication and accounts

### 3.1 Account creation

Users must create accounts using their university e-mail address.

* only e-mail addresses from approved university domains are accepted.

* Initially this is ony `unibas.ch`, includung `stud.unibas.ch`

### 3.2 Login

Users log in using their e-mail address and password.

### 3.3 Role assignment

The system must distinguish between students, supervisors and administrators.

* students are the default role for self-registration.
* student accounts can be promoted to supervisors or administrators by an existing administrator;


### 3.4 Security requirements

* Passwords must never be stored in plain text.
* Sessions must be protected against common web attacks.
* Uploaded files must not be executable by the web server.
* Access control must prevent students from accessing supervisor pages or other students’ submissions.

### 3.5 Password recovery

* Passwords can be recovered using the account e-mail as a recovery e-mail address

## 4. Course structure

The content hierarchy is:

```text
Course
└── Tutorial / Session
    └── Exercise
        └── Exercise variant(s)
            └── ExercisePart(s)
```

### 4.1 Course

A course has:

* unique ID;
* title;
* description, optional;
* active/inactive status;
* creation timestamp;
* creator ID;
* one or more assigned supervisors;

### 4.2 Tutorial / Session

A tutorial belongs to one course.

A tutorial has:

* unique ID;
* course ID;
* title;
* ordering/index within the course;
* active/inactive status;
* creation timestamp.

### 4.3 Exercise

An exercise belongs to one tutorial.

An exercise has:

* unique ID;
* tutorial ID;
* title;
* ordering/index within the tutorial;
* active status;
* lock status;
* creation timestamp;
* last modified timestamp.

## 5. Exercise variants

Each exercise can have multiple alternative versions of the exercise text.

Each variant consists of one or more exercise parts.

Each variant has:
* unique ID;
* exercise ID;
* optional shared text or description;
* optional images;

Each variant contains multiple ExerciseParts.

### 5.1 Exercise parts

Each ExerciseVariant consists of one or more ExerciseParts.

Each part has:
* label (e.g. "a", "b", "c", "d");
* ordering within the variant;
* prompt text;
* answer type (numerical or document upload);
* reference solution (if numerical, double precision);
* tolerance (if numerical, double precision);
* available points;

The total score for an ExerciseVariant is the sum of the points of its parts.

## 6. Exercise answer types

### 6.1 Numerical answer

For numerical-answer exercises:

* the student enters one value per ExercisePart in double-precision;
* each part is checked independently against its double-precision reference solution;
* correctness is determined per part;
* scores are assigned per part and summed;
* the supervisor provides a reference answer per ExercisePart;
* the system automatically checks the submitted answer against the reference answer with double-precision;
* the result is stored immediately.
* scientific and fortran-notation numerical values can be parsed as user input

The system should support a tolerance mechanism.

Initial implementation:

* absolute tolerance, configurable per part;

Stored result should include:

* submitted value;
* reference value;
* tolerance used;
* correct/incorrect status;
* score (based on points);
* submission timestamp.

### 6.2 Document upload

For document-upload ExerciseParts:

* the student uploads a file;
* the file is stored securely;
* the supervisor can download/review the uploaded file;
* the supervisor manually enters a result/score.

Stored ResultPart should include:

* file name;
* stored file path or object key;
* upload timestamp;
* supervisor-entered score;
* supervisor feedback, optional;
* grading timestamp;
* grading supervisor ID.

## 7. Student workflow

Students should be able to:

1. Register with a university e-mail address.
2. Log in.
3. View available courses.
4. Select a course.
5. View tutorials/sessions in the course.
6. View currently active exercises.
7. Select an exercise.
8. Receive one randomly assigned variant of the exercise.
9. Submit either:

   * a numerical answer; or
   * a document upload.
10. See whether numerical answers were correct.
11. View a summary of completed exercises and scores.
12. Request a password reset e-mail


## 8. Supervisor workflow

Supervisors should be able to:

1. Log in.
2. Open supervisor dashboard with tree editor for course/tutorial/exercise/variant/part.
3. Create a course.
4. For each course:
   * Enter a course title;
   * Add tutorials to the course;
5. For each tutorial:
   * enter a tutorial title;
   * deactivate or activate the tutorial;
   * add exercises to tutorials.
6. For each exercise:
   * enter exercise title;
   * add exercise variants to exercises.
   * deactivate or activate the exercise.
7. For each variant:
   * enter an exercise variant text using rich text with bold/italic/sub/sup,links,special character,font-size selector,file insertion link;
   * upload images if needed;
   * add exercise parts to variant.
8. For each exercise part:
   * enter an exercise part text using rich text with bold/italic/sub/sup,links,special character,font-size selector,file insertion link;
   * upload images if needed;
   * choose input type: numerical answer or document upload;
   * enter reference solutions for numerical exercise parts;
   * set tolerance for numerical checking;
   * set points available;
9. Upload files to media/content and browse existing files in media/content to insert into variant and part text
10. View student submissions per exercise.
11. Download uploaded student files.
12. Manually grade document-upload exercises.
13. View summary results per course.
14. Delete incorrect or unwanted results.
15. Archive results to clear current result pages.
16. Browse archived results later.
17. Request a password reset e-mail

## 9. Administrator workflow

Administrators should be able to do the same as supervisors, plus additionally:

1. View existing user accounts
2. For each user account be able to:
    * assign or remove supervisor rights
    * assign or remove administrator rights
    * reset the user's password
3. Request a password reset e-mail
4. Edit or delete existing exercises, tutorials or courses of all users

## 9. Results and grading

### 9.1 Result records

Each student submission creates or updates a result record.

Each Result consists of one or more ResultParts.

Each ResultPart corresponds to one ExercisePart and stores:
* submitted value (double precision);
* correctness;
* score;
* submission timestamp;
* uploaded file reference, if applicable;
* reference value used (double precision);
* tolerance used (double precision);
* manual grading status;
* graded timestamp;
* feedback, optional;
* submitted timestamp;

The total Result score is the sum of the scores of its ResultParts.

A result record should include:

* unique ID;
* student ID;
* course ID;
* tutorial ID;
* exercise ID;
* assigned variant ID;
* total score;
* correctness status;
* archived flag or archive batch ID.

### 9.2 Course summary page

For each course, supervisors need a summary page showing:

* students enrolled or participating in the course;
* exercises in the course;
* result/score for each exercise per student;
* completion status;
* manual grading status for uploaded-file exercises;
* links to uploaded documents where applicable.

The summary page should support:

* filtering by tutorial/session;
* filtering by student;
* filtering by exercise;
* identifying missing submissions;
* exporting results, optional later feature.

Current implemented selection behavior for `/supervisor/courses/<id>/summary/`:

* only current (non-archived) results are included;
* only results for active exercises are included;
* when a tutorial filter is set, only results from exercises in the selected tutorial are included;
* the student list is derived from students who already have at least one included result in the current filter scope;
* students with no included result in scope are not listed in the table;
* selecting a student filter restricts table rows to that student only.

### 9.3 Deleting results

Supervisors can delete results (hard deletion).

### 9.4 Archiving results

Supervisors can archive results to clear current result pages while preserving historical data.

Archived results should:

* no longer appear in default current-results views;
* remain browsable through an archive interface;
* preserve scores, submissions, uploaded files, timestamps, and assigned variants.

## 10. Exercise activation

Supervisors can control exercise availability.

Each exercise should have at least one availability state:

* inactive: students cannot attempt it;
* active: students can attempt it.

Possible future states:

* draft;
* scheduled;
* closed but visible;
* archived.

Initial implementation:

* use a simple boolean `is_active` field.

## 11. File uploads

The system must support file uploads for:

* supervisor-provided exercise images;
* student-uploaded solution documents.

Requirements:

* restrict allowed file types;
* restrict maximum file size;
* store files outside executable web paths;
* associate each file with the correct user, exercise, and result;
* prevent students from accessing files uploaded by other students;

Initial file types:

* images: PNG, JPEG, SVG if allowed safely;
* student documents: PDF, DOCX, PNG, JPEG, TIFF, possibly ZIP if required later.

## 13. Deployment environment

The application will be hosted on:

* Ubuntu Linux server;
* local web server;
* behind a university firewall.

Assumptions:

* HTTPS is handled by the local web server;
* the application is not exposed to the public internet;
* nevertheless, normal web security practices are required.

Potential deployment stack:

* reverse proxy: Nginx or Apache;
* application server: depends on chosen framework;
* database: PostgreSQL recommended for production, SQLite acceptable for early prototype;
* file storage: local filesystem initially, with clear directory layout and backups.

## 14. Suggested initial technical direction

This section is provisional and can be changed.

A suitable initial stack could be:

* Backend: Python FastAPI or Django;
* Database: SQLite for prototype, PostgreSQL for deployment;
* Frontend:

  * server-rendered templates for simplicity; 
* Authentication:

  * framework-supported password authentication;
  * later optional integration with university single sign-on if available.

* use Django for built-in admin, authentication, forms, permissions, and file upload handling;

## 15. Minimum viable product

The first working version should include:

1. User registration with university e-mail validation.
2. Login/logout.
3. Student, supervisor and administrator roles.
4. Supervisor can create courses.
5. Supervisor can create tutorials within courses.
6. Supervisor can create exercises within tutorials.
7. Exercise supports:

   * title;
   * text variant(s);
   * numerical answer type;
   * document-upload type;
   * active/inactive status.
8. Students can view courses/tutorials/exercises.
9. Students can submit numerical answers.
10. Numerical answers are automatically checked.
11. Students can upload file solutions for upload-type exercises.
12. Supervisors can view submissions.
13. Supervisors can manually grade uploaded submissions.
14. Supervisors can view a course result summary.
15. Supervisors can archive results.
16. Administrators can manage student and supervisor accounts
17. Administrators can modify or delete courses, tutorials or exercises of any user

## 16. Features explicitly out of scope for first version

The following should not be implemented:

* payment processing;
* public course marketplace;
* complex learning analytics;
* real-time collaboration;
* chat/messaging;
* mobile app;
* plagiarism detection;
* symbolic mathematics checking;
* automatic grading of uploaded documents;
* integration with university single sign-on;
* full LMS replacement.


