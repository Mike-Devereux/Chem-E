# DEVELOPMENT.md

## Local development setup

This project is developed locally using Django’s built-in development server.

Production deployment will use Apache2, but Apache2 is not required during development.

## Requirements

- Python 3.11 or newer
- Git
- Virtual environment
- SQLite for early development
- Pillow for ImageField

## Environment

- django is installed using uv to /home/devereux/chem-E
- SQLite3 is to be used in the same uv environment

## Setup
- To set up and launch django in a new venv using uv:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
cd ~
uv venv chem-E
source ~/chem-E/bin/activate
uv pip install django
```

- To test Django works (subsequently test connection to http://127.0.0.1:8000):
```bash
django-admin startproject config .
python manage.py runserver
```
- To start cursor in the new env, open a second terminal, then:
```bash
cd ~/chem-E
source bin/activate
cursor
```
- To link to Github, create a new repository on the Github website, then open a terminal in cursor and:
```bash
git remote add origin https://github.com/Mike-Devereux/Chem-E
git status
git branch -M main
git add <filelist>
git commit -m "Initial commit"
git push -u origin main
```
- Each time cursor is restarted, use the files SPEC.md, TODO.md and DECISIONS.md to record the context required by the AI
- Password reset emails use Django's console email backend in development, so reset links are printed in the terminal running `python manage.py runserver`.
- Password reset behavior uses Django built-ins only:
  - user-requested reset via `/password-reset/` (email link workflow),
  - admin-triggered reset via Django admin user change page ("change password").
- No custom password reset logic is implemented in this project.
- Load the context by starting the first prompt with something like:

> Read SPEC.md, TODO.md, DECISIONS.md and the current Django project structure.
>
> We are building a Django-based e-learning tool named Chem-E.
>
> The current goal is ...
>
> Do not make broad changes. Before editing, summarize the files you intend to modify.

## Demo data

To populate the local database with sample courses, tutorials, exercises, and variants:

```bash
uv run python manage.py seed_demo_data
```

## Local upload testing

Uploaded files are stored under `MEDIA_ROOT` in the local `media/` directory.

The `media/` directory is for development data and should not be committed to Git.

## Supervisor course/tutorial/exercise/variant editing should use a tree format

Rather than relying on Django built-ins, a tree structure of course->tutorial->exercise->exercise variants should be shown to supervisors when creating and editing new content