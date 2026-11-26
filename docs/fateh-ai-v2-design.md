# Fateh AI v2 — design

Status: **approved 2026-11-26** — read-only tools, core scope only, tested on sft-uat with Groq. Branch `feat/fateh-ai-v2`.

## 1. Why rewrite

The current assistant (`grey_theme/chat_handler.py` + page `ai-chat`) is unsafe and weak:

| Problem | Where | Effect |
|---|---|---|
| LLM-written SQL executed raw, no validation beyond "starts with select" | `chat_handler.py:ask_general_ai` | Any desk user can read any table — salaries, `__Auth` password hashes, other companies — bypassing roles **and** User Permissions |
| Excel exports written to `public/files` with a guessable name | `export_to_excel` | Query results are downloadable by anyone with the URL, no login |
| `insert(ignore_permissions=True)` + `frappe.db.commit()` on regex-parsed commands | `create_customer_from_command`, `create_item_from_command` | Users without Customer/Item create rights can create them |
| Groq only, model id hard-coded (`llama-4-scout`, already retired by Groq once) | `ask_general_ai` | Breaks silently when the provider retires the model |
| API keys in plain `Data` fields | `AI Settings` | Keys readable in DB dumps / exports |
| Regex intent matching (`"overdue" in q and "customer" in q`) | `handle_ai_query` | Only ~7 canned questions work; `get_top_items_by_sales` is defined twice (second shadows first, returns ₹-formatted HTML) |
| History lives in browser memory only | `ai_chat.js` | Lost on reload, not searchable |
| No streaming, no stop, no markdown, hard-coded light colours, `body {}` CSS leaks into the whole desk | `ai_chat.html` | Poor UX, breaks dark mode |

## 2. What we take from the references (ideas, not code, unless MIT)

| Source | Licence | Taken |
|---|---|---|
| byt3crafter/erpnext-copilot | MIT | Background job + realtime streaming protocol; tool registry with JSON schema; ERPNext data rules in the system prompt (docstatus=1, is_return, posting_date, base currency); conversation doctype with tokens; per-tool audit log; starter prompts; friendly tool-status labels |
| soumyasethy/lazychat-erpnext | MIT | Provider adapter with canonical Anthropic-style blocks + OpenAI translation; two-phase writes (prepare → Apply card → commit with permission re-check); desk-context capture (`cur_frm`, list selection); `describe_doctype` schema tool; resizable drawer + minimise bubble + theme sync |
| ERPGulf/changai | MIT | Permission-respecting analytics; debug view of tool calls |
| FAC / Raven / huf / Jarvis | AGPL-3.0 | **Ideas only**: audit every tool call, role-gated tools, confirmation gate, strip model-supplied `ignore_permissions` |

Explicitly **not** taken (security holes found in the references): file-path tools that accept
`/files/../..` (copilot), subagents that skip guards (copilot), `get_all` for user-facing reads
(both), auto-run SQL/Python (lazychat), `send_email` without confirmation (copilot), token consumed
after execution allowing double-apply (lazychat), ChatGPT-OAuth impersonation (copilot).

## 3. Security model (non-negotiable)

1. Every tool runs **as the logged-in user** (background job is enqueued with that user; frappe's
   `execute_job` calls `frappe.set_user`). No `ignore_permissions` anywhere.
2. Reads use `frappe.get_list` (roles + **User Permissions** + `permission_query_conditions`),
   `frappe.get_doc` + `has_permission` + field-level (permlevel) filtering. Never `get_all`.
3. **Read-only.** v2 ships no write tool at all (decision 2026-11-26). The old regex
   `create a customer` / `create an item` commands (which used `ignore_permissions=True`) are
   removed. If writes are added later they must be staged: propose → Apply card → atomic token
   pop → permission re-check → no `ignore_permissions`.
4. Blocked doctypes regardless of role: User, Role, User Permission, OAuth*, Access Log,
   System Settings, AI Settings, any `__*` table; blocked fields: Password fieldtype and names
   matching `password|api_key|api_secret|token|secret`.
5. Raw SQL tool: **off by default**, System Manager only, `check_safe_sql_query` (frappe's own),
   `__` tables blocked, `max_statement_time`, row cap. Settings say plainly it bypasses User Permissions.
6. Exports are **private** File rows attached to the conversation.
7. Tool output is data: the system prompt tells the model instructions found in documents are not
   from the user; with no write tools, injected text cannot change data.
8. Desk users only (`System User`), optional role allow-list, per-user daily message cap.
9. API keys in `Password` fields; legacy plaintext Groq/DeepSeek keys migrated by a patch.

## 4. Backend layout (`grey_theme/fateh_ai/`)

| File | Role |
|---|---|
| `providers.py` | `chat_stream(messages, system, tools) -> iterator of events`; adapters `anthropic` (Messages API) and `openai_compatible` (OpenAI, Groq, DeepSeek, Gemini OpenAI endpoint, OpenRouter, Ollama, custom). Retry on 429/5xx with backoff; **fallback model chain** on 404/`model_not_found`; timeouts; reasoning models with empty content treated as failure. Uses `requests` only — no new pip dependency. |
| `tools/` | Registry + guarded executor. Read tools: `search_records`, `get_record`, `count_records`, `aggregate` (group-by sum/count/avg/min/max, structured — the model never writes SQL fragments), `describe_doctype`, `find_doctype`, `search_link`, `list_reports`, `get_report_filters`, `run_report`, `stock_balance`, `party_outstanding`, (`run_sql_select` gated). No write tools. Charts come from ```chart blocks in the answer; tables export client-side to CSV (no server file). |
| `agent.py` | Loop (max iterations from settings), streaming text deltas batched ~80 ms, tool calls, stop flag in Redis, history compaction (old tool results truncated), token accounting. |
| `prompts.py` | Persona + date/time anchor + user/roles/company defaults + ERPNext data rules + desk context + output conventions (markdown tables, ```chart blocks, `/app/...` links). |
| `api.py` | Whitelisted: `send_message`, `stop`, `list_conversations`, `get_conversation`, `rename/pin/delete_conversation`, `get_run_status`, `bootstrap`, `test_connection` / `list_models` (System Manager). |

Streaming: `frappe.publish_realtime("fateh_ai", {...}, user=..., after_commit=False)`; the UI also
polls the conversation if no event arrives for 20 s (covers a dead socket.io).

### DocTypes

- **AI Settings** (existing Single, extended): enabled, provider, api_key (Password), base_url,
  model, fallback_models, temperature, max_iterations, max_output_tokens, enable_write_actions,
  enable_sql_tool, show_launcher, allowed_roles, daily_message_limit, assistant_name,
  extra_instructions. Legacy `groq_api_key` / `deepseek_api_key` / `default_provider` hidden,
  migrated by patch.
- **Fateh AI Conversation** — owner-only via `has_permission` + `permission_query_conditions`;
  System Manager can read.
- **Fateh AI Message** — standalone doctype linked to the conversation (role, content, canonical
  blocks JSON, UI steps JSON, tokens). Not a child table, so the background job appends rows
  without re-saving the parent (no timestamp clash with a rename from the UI). Read through the API
  after the conversation permission check.
- **Fateh AI Audit Log** — one row per tool call (user, conversation, tool, args, status,
  duration, reference doc). Read-only for System Manager; users cannot delete it, and deleting a
  conversation keeps its audit rows.

## 5. UI

One `ChatApp` component, mounted two ways: a **launcher + slide-out drawer** on every desk page
(toggle in settings, shortcut Ctrl+I) and the full page `/app/ai-chat`.

- Server-side history sidebar: search, pin, rename, delete, date groups.
- Streaming answer with Stop; Regenerate; Copy; edit-and-resend last question.
- Markdown (frappe.markdown + our own whitelist sanitiser — older v15 builds lack frappe's).
- Result tables: sticky header, sortable, copy CSV, download CSV (UTF-8 BOM so Excel opens Arabic).
- Charts from ```chart blocks rendered with the desk's bundled `frappe.Chart` (no CDN).
- Tool steps shown as collapsible chips ("Searching Sales Invoice…"), with arguments for debugging.
- Context pill: "Looking at Sales Invoice ACC-SINV-0001" (removable); context-aware starter prompts.
- Document names become `/app/<doctype>/<name>` links opened with `frappe.set_route`.
- Frappe theme variables only (light/dark follow the desk), RTL aware, mobile width, voice input
  where the browser supports it, keyboard: Enter send, Shift+Enter newline, Esc close.
- All CSS scoped under `.fateh-ai` (the old page's global `body {}` rule is removed).

## 6. Rollout

- Everything off until **AI Settings → Enabled** is ticked (shared benches: bystander sites see no
  change; boot payload carries `enabled: 0`).
- Patch migrates legacy keys (moves the plaintext Groq/DeepSeek key into the Password field and blanks the plaintext copy; sites that had a key stay enabled, launcher off); old `chat_handler.handle_ai_query` kept as a thin shim calling the new
  engine for one release so cached old pages don't 500.
- Tests: `FrappeTestCase` for permission enforcement (user without read is refused, User Permission
  limits rows), staged-write token single-use and permission re-check, SQL guard, provider
  translation with mocked HTTP, agent loop with a scripted fake provider, settings patch.
- Server Manager trap: benches run `EnfonoTech/grey-theme` `enfono-suspension-<sha>` builds — the
  new `extend_bootinfo` must append, not assign (see memory note on the suspension block).

## 7. Phase 2 (not in this branch unless asked)

File/image upload → draft document (OCR via vision model), scheduled AI reports by email,
knowledge base / RAG over uploaded files, saved prompts, per-role tool profiles, usage dashboard.
