# DEVELOPMENT.md

## Local development setup

This project is developed locally using Django’s built-in development server.

Production deployment will use Apache2, but Apache2 is not required during development.

## Requirements

- Python 3.11 or newer
- Git
- Virtual environment
- SQLite for early development

## Setup
- To set up and launch django in a new venv using uv:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
cd ~
uv venv chem-E
source ~/chem-E/bin/activate
uv pip install django
django-admin startproject config .
python manage.py runserver
```
- To start cursor in that env, open a second terminal with django still running, then:
```bash
cd ~/chem-E
source bin/activate
cursor
```

