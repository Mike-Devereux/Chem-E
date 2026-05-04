# Decisions

- Use Django instead of FastAPI (reason: built-in admin)
- Use SQLite during development

- Django project is named "chem_e"
- Django app is named "core"

- A custom Django User model is used with unique e-mail address and without username

- ImageField is used for image uploads

- Courses may have multiple supervisors.
- Course.creator records who created the course.
- Course.supervisors defines which supervisors can manage the course.
- Administrators can manage all courses.