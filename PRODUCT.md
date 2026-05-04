# TableTalker — Product Brief

## What it is

TableTalker is a data analysis agent. Give it a CSV or Excel file and a
plain-English question, and it returns an interactive HTML report — with
charts, a written narrative, and the ability to ask follow-up questions
that drill deeper into the same data.

## Who it's for

Operators, analysts, and decision-makers who need answers from spreadsheets
without writing pandas code or waiting on a data team. Anyone who has ever
opened a CSV in Excel, scrolled around, and thought "what is this telling me?"

## What makes it different

- **Reproducible findings.** Every number in the report is backed by code
  the user can re-run. If a claim cannot be reproduced from the data, the
  agent says so instead of guessing.
- **Follow-up native.** Reports are not the end — they are the start of a
  conversation. The agent keeps the dataset in working memory and answers
  follow-ups in the same context.
- **Exportable, shareable.** A report is a single self-contained HTML file
  with Plotly charts embedded — no server needed to view it later.

## Out of scope

- Dashboards that auto-refresh against a live database.
- Real-time streaming data.
- Multi-user collaboration on the same report.
