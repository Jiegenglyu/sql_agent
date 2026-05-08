# sql_agent

Initial repository for an SQL-focused agent project.

## Goals

- Translate user questions into SQL against explicitly configured data sources.
- Keep database credentials and API keys outside source control.
- Make query execution auditable, testable, and easy to configure per environment.

## Local Setup

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

Copy the example environment file before adding local secrets:

```bash
cp .env.example .env
```

## Configuration

Use `.env` for local configuration. Do not commit `.env`.

```bash
DATABASE_URL=
LLM_API_KEY=
```

## Status

This repository has just been initialized. Application code and tests can be added once the agent scope is defined.
