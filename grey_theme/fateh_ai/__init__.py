# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt
"""Fateh AI — the desk assistant shipped with Grey Theme.

Layout:
    config.py     settings, provider presets, access rules
    providers.py  LLM adapters (OpenAI-compatible + Anthropic), streaming, retries, model fallback
    tools.py      read-only, permission-guarded ERP tools the model can call
    prompts.py    system prompt and desk-context briefing
    agent.py      the background agent loop (streams over frappe realtime)
    api.py        whitelisted endpoints used by the chat UI
"""
