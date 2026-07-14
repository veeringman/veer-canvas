# Prep Studio

A modular Python + HTML + CSS + JavaScript web app for IIT JEE + beginner programming learning. It includes:

- Three primary tabs: Class 11, Class 12, Programming
- Daily syllabus-oriented learning tasks for Physics, Chemistry, and Mathematics
- Daily practice tasks that adapt difficulty based on your recorded performance
- Progress logging (minutes, questions, accuracy, notes)
- 7-day planning view and progress analytics
- Best-practice question bank with answers, full explanations, and visual diagrams
- Beginner programming tracks with notebook-style exercises and live code runner
- LLM-powered chatbot dock for every authenticated page
- Multi-user login and local authentication (extensible toward social/IdP)
- App-wide annotation and feedback system with automatic action handling
- Configurable model selection in Settings for LLM-ready resolution layer
- Model registry with free/paid labeling and auto-sync for new interesting models

## Modular Architecture

Core modules are now separated for cleaner maintenance and future extension:

- `core/config.py`: shared constants, syllabus, and programming track definitions
- `core/auth.py`: auth helpers and decorators
- `core/planning.py`: daily planning + analytics service logic
- `core/llm.py`: LLM provider integration adapter
- `app.py`: route composition, database migrations, and app bootstrap

## Tech Stack

- Python (Flask)
- SQLite
- HTML (Jinja templates)
- CSS (custom responsive UI)
- JavaScript (table filtering and progress animation)

## Run Locally

1. Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Start the server:

```bash
python app.py
```

4. Open your browser at:

- http://127.0.0.1:5000

5. Create an account from `/register`, then login.

## Forgot Password Email Setup

The forgot-password flow sends a temporary password by SMTP. Configure these variables in `.env`:

- `MAIL_SERVER` (example: `smtp.gmail.com`)
- `MAIL_PORT` (example: `587`)
- `MAIL_USE_TLS` (`true` recommended)
- `MAIL_USERNAME` (SMTP account username/email)
- `MAIL_PASSWORD` (SMTP password or app password)
- `MAIL_FROM` (sender address shown to users)

Quick Gmail setup:

1. Enable 2-Step Verification on the Gmail account.
2. Create an App Password in Google Account security.
3. Set `MAIL_USERNAME` to your Gmail address.
4. Set `MAIL_PASSWORD` to the 16-character app password.
5. Restart the app.

If SMTP is not configured, the app falls back to showing a temporary password message for local development.

## How Daily Tasks Are Generated

- The app rotates through Class 11 chapter lists for each subject.
- It checks your latest logs for each subject.
- If your recent accuracy or study time is low, tasks become foundation-focused.
- As your metrics improve, task complexity increases.

## Question Bank Standards

- Curated by subject and chapter with three complexity levels: Level 1, Level 2, Level 3
- Each question includes answer key and stepwise explanation
- Selected questions include diagram/visualization support for conceptual clarity
- Filters let you practice by subject and complexity with focused revision sessions

## Feedback and Resolution Workflow

- Every major page and content block includes a report/review widget.
- Feedback is stored with page, section, item id, severity, and issue type.
- The app takes immediate actions for selected issue types, such as:
	- Triggering study material sync for outdated/incorrect content reports.
	- Triggering link verification for broken source reports.
- A Feedback Center page tracks statuses and actions.

## Settings and Model Selection

- Open Settings from top navigation.
- Choose the model used for LLM-based recommendation metadata.
- Settings now show model provider, capability, and whether each model is free or paid.
- Use "Sync New Interesting Models" to pull and add candidate models from web catalog sources while keeping curated defaults.
- Current model selection is shown in Feedback Center and used in generated recommendation notes.

## Learning Notes

You can inspect and learn from:

- `app.py`: Flask routes, SQLite usage, and task-generation logic
- `templates/`: HTML + Jinja templating
- `static/css/style.css`: Visual design and responsive layout
- `static/js/app.js`: Client-side interactivity
