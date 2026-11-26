## Grey Theme App

Grey Theme

## Features

Two optional desk UI enhancements, both driven by a single settings page —
**Grey Theme UI Settings** (Single DocType, module *Grey Theme*). Both are off by
default; with the switches off the desk is stock Frappe.

**Grid Enhancer** — child tables (the Items grid on a Sales Invoice, etc.) render
the columns Frappe would drop past its 11-unit budget, sized by Frappe's own
proportions scaled to the container. Once those widths no longer fit — a narrow
window, a Split View pane, browser zoom — the grid scrolls horizontally with the
heading and filter rows locked to the body, and columns pinned from
*Configure Columns* stay at the left edge.

**Split View** — a list view gains a *Split View* entry in its views menu: list on
the left, the selected document's form on the right, with a draggable splitter
whose width is remembered in that browser's local storage. DocTypes can be
excluded from it.

Full settings reference, install/upgrade steps, and the manual QA checklist:
[docs/ui-features.md](docs/ui-features.md).

## Fateh AI assistant

A read-only ERP assistant, off until **AI Settings → Enabled** is ticked.

- **Any provider**: Groq, OpenAI, Anthropic Claude, Google Gemini, DeepSeek, OpenRouter,
  Ollama or any OpenAI-compatible endpoint. Keys are stored encrypted. A fallback model list
  takes over when a provider retires a model. *Test Connection* and *Fetch Models* buttons
  are on the settings form.
- **Tools instead of generated SQL**: the model looks up DocTypes and fields, searches,
  counts, totals and groups records, reads documents, finds IDs by name, and runs reports.
  It also has stock balance and outstanding-invoice helpers. Every tool runs as the asking
  user, with roles, User Permissions and field-level permissions applied. There are no
  write tools.
- **Chat UI**:
  - streamed answers with a Stop button, and tool steps you can open to see each query and
    its rows;
  - markdown tables you can sort, copy or download as CSV, and inline charts;
  - document links that open in the desk;
  - saved, searchable chat history;
  - voice input, dark mode and RTL support.
- **Everywhere in the desk**: a floating launcher and Ctrl+I open a side drawer that knows
  the current form, list (including selected rows) or report. A full page lives at
  `/app/ai-chat`.
- **Governance**: optional role allow-list and per-user daily limit. Every tool call is
  written to **Fateh AI Audit Log**, which Log Settings prunes after 90 days. Raw SQL is off
  by default, and when enabled it is available to System Managers only.

Design and security model: [docs/fateh-ai-v2-design.md](docs/fateh-ai-v2-design.md).

#### License

mit
