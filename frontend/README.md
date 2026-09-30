# AWGP Audiobook Pipeline dashboard

This directory contains the React/Vite dashboard for editors and Checkers. The
Python API in the repository root must be running before using the dashboard.

## Local development

From this directory:

~~~sh
npm ci
npm run dev
~~~

Open the local URL printed by Vite. During development, `/api` is proxied to
`http://localhost:8000`; start the API in another terminal from the repository
root:

~~~sh
uvicorn api:app --host 127.0.0.1 --port 8000
~~~

For a separately hosted API, set `VITE_API_BASE` before `npm run dev` or
`npm run build`.

## Available commands

- `npm run dev` — development server with hot reload.
- `npm run build` — production build in `dist/`.
- `npm run preview` — serve the production build locally.
- `npm test` — frontend tests.
- `npm run lint` — Oxlint checks.

## Review workflow

Sign in, open a project, and use the stage controls to monitor pipeline work.
Editors can update OCR, segments, pronunciation, and prosody, then regenerate
the affected stages. Checkers should listen to the current mastered candidate,
create issues against that candidate, and submit a decision only after comparing
the audio with the source book. When a later candidate is generated, unresolved
issues are carried forward automatically; verify them on the new candidate before
approval.

See the repository [README](../README.md) and the [feedback workflow guide](../docs/feedback-workflow-implementation-guide.md)
for setup, CLI recovery, candidate lineage, and conflict handling.
