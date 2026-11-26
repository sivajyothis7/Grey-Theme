// Copyright (c) 2026, Enfono Technologies and contributors
// For license information, please see license.txt
//
// Fateh AI desk bundle (loaded through app_include_js as "fateh_ai.bundle.js").
// Exposes grey_theme.fateh_ai.ChatApp for the /app/ai-chat page and installs the launcher.
// With AI Settings disabled the launcher installs nothing.

import { ChatApp } from "./fateh_ai/chat_app";
import { get_desk_context } from "./fateh_ai/launcher";

frappe.provide("grey_theme.fateh_ai");
grey_theme.fateh_ai.ChatApp = ChatApp;
grey_theme.fateh_ai.get_desk_context = get_desk_context;
