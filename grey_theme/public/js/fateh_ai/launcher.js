// Copyright (c) 2026, Enfono Technologies and contributors
// For license information, please see license.txt
//
// Desk-wide entry points for Fateh AI: a floating launcher button, a resizable side drawer
// that hosts the ChatApp, and the Ctrl+I shortcut. Everything is gated on
// frappe.boot.fateh_ai (published by grey_theme.boot) — with the assistant disabled, or for a
// user outside the allowed roles, nothing is added to the page.

import { ChatApp } from "./chat_app";
import { icon, tpl } from "./render";

const WIDTH_KEY = "fateh_ai_drawer_width";
const MIN_WIDTH = 360;

function storage_get(key) {
	try {
		return window.localStorage.getItem(key);
	} catch (e) {
		return null;
	}
}

function storage_set(key, value) {
	try {
		window.localStorage.setItem(key, value);
	} catch (e) {
		/* private mode / blocked storage */
	}
}

function strip(html) {
	return String(html || "")
		.replace(/<[^>]*>/g, "")
		.trim()
		.slice(0, 140);
}

// What the user is looking at, so "this invoice" / "these rows" work. The server re-checks
// permissions on every name before it reaches the model.
export function get_desk_context() {
	const route = (frappe.get_route && frappe.get_route()) || [];
	const ctx = { route: route.slice(0, 4).map((p) => String(p)) };
	const view = route[0];

	if (view === "Form" && route[1]) {
		ctx.view = "Form";
		ctx.doctype = route[1];
		const frm = window.cur_frm;
		if (frm && frm.doctype === route[1] && frm.doc && !frm.is_new()) {
			ctx.docname = frm.docname;
			try {
				ctx.title = strip(frm.get_title ? frm.get_title() : "");
			} catch (e) {
				/* ignore */
			}
		}
	} else if (view === "List" && route[1]) {
		ctx.view = "List";
		ctx.doctype = route[1];
		const lv = window.cur_list;
		if (lv && lv.doctype === route[1]) {
			try {
				ctx.selected = (lv.get_checked_items(true) || []).slice(0, 20);
				const f = lv.get_filters_for_args ? lv.get_filters_for_args() : lv.filters;
				if (Array.isArray(f) && f.length) ctx.filters = f.slice(0, 10);
			} catch (e) {
				/* ignore */
			}
		}
	} else if (view === "query-report" && route[1]) {
		ctx.view = "Report";
		ctx.report = route[1];
		const qr = frappe.query_report;
		if (qr && qr.report_name === route[1] && qr.get_filter_values) {
			try {
				ctx.filters = qr.get_filter_values(false);
			} catch (e) {
				/* ignore */
			}
		}
	}
	return ctx;
}

class Launcher {
	constructor() {
		this.boot = frappe.boot.fateh_ai || {};
		this.app = null;
		this.drawer = null;
		this.button = null;
		this.is_open = false;
	}

	init() {
		if (!this.boot.enabled || !this.boot.allowed) return;
		frappe.provide("grey_theme.fateh_ai");
		grey_theme.fateh_ai.open = () => this.open();
		grey_theme.fateh_ai.toggle = () => this.toggle();

		if (this.boot.launcher) this.make_button();
		this.bind_shortcut();
		this.bind_route();
	}

	make_button() {
		const name = frappe.utils.escape_html(this.boot.name || "Fateh AI");
		this.button = tpl(
			`<button type="button" class="fai-launcher" title="${name} (Ctrl+I)" aria-label="${name}">${icon("sparkle")}</button>`
		).firstElementChild;
		this.button.addEventListener("click", () => this.toggle());
		document.body.append(this.button);
		this.sync_button();
	}

	bind_shortcut() {
		if (!frappe.ui.keys || !frappe.ui.keys.add_shortcut) return;
		frappe.ui.keys.add_shortcut({
			shortcut: "ctrl+i",
			action: () => {
				this.toggle();
				return true;
			},
			description: __("Open {0}", [this.boot.name || "Fateh AI"]),
			ignore_inputs: false,
		});
	}

	bind_route() {
		const on_change = () => {
			this.sync_button();
			if (this.app) this.app.refresh_context(true);
		};
		if (frappe.router && frappe.router.on) frappe.router.on("change", on_change);
		else $(window).on("hashchange popstate", on_change);
	}

	on_chat_page() {
		const route = (frappe.get_route && frappe.get_route()) || [];
		return route[0] === "ai-chat";
	}

	sync_button() {
		if (!this.button) return;
		this.button.hidden = this.is_open || this.on_chat_page();
	}

	ensure_drawer() {
		if (this.drawer) return;
		this.drawer = tpl(
			`<div class="fai-drawer" role="dialog" aria-label="${frappe.utils.escape_html(this.boot.name || "Fateh AI")}"><div class="fai-drawer-grip" title="${frappe.utils.escape_html(__("Drag to resize"))}"></div></div>`
		).firstElementChild;
		document.body.append(this.drawer);
		const saved = parseInt(storage_get(WIDTH_KEY), 10);
		if (saved) this.set_width(saved);
		this.bind_resize(this.drawer.querySelector(".fai-drawer-grip"));

		this.app = new ChatApp({
			parent: this.drawer,
			mode: "drawer",
			get_context: get_desk_context,
			on_close: () => this.close(),
			on_expand: (conversation) => {
				this.close();
				grey_theme.fateh_ai.pending_open = conversation || null;
				Promise.resolve(frappe.set_route("ai-chat")).then(() => {
					const page_app = grey_theme.fateh_ai.page_app;
					if (conversation && page_app && grey_theme.fateh_ai.pending_open) {
						grey_theme.fateh_ai.pending_open = null;
						page_app.open(conversation);
					}
				});
			},
		});
	}

	set_width(px) {
		const max = Math.max(MIN_WIDTH, window.innerWidth - 80);
		const w = Math.min(Math.max(px, MIN_WIDTH), max);
		this.drawer.style.setProperty("--fai-drawer-width", `${w}px`);
		return w;
	}

	bind_resize(grip) {
		let start_x = 0;
		let start_w = 0;
		const rtl = document.documentElement.dir === "rtl";
		const move = (e) => {
			const dx = e.clientX - start_x;
			const w = this.set_width(start_w + (rtl ? dx : -dx));
			this._last_w = w;
		};
		const up = () => {
			document.removeEventListener("pointermove", move);
			document.removeEventListener("pointerup", up);
			document.body.classList.remove("fai-resizing");
			if (this._last_w) storage_set(WIDTH_KEY, String(this._last_w));
		};
		grip.addEventListener("pointerdown", (e) => {
			start_x = e.clientX;
			start_w = this.drawer.getBoundingClientRect().width;
			document.body.classList.add("fai-resizing");
			document.addEventListener("pointermove", move);
			document.addEventListener("pointerup", up);
			e.preventDefault();
		});
	}

	open() {
		if (this.on_chat_page()) return;
		this.ensure_drawer();
		this.is_open = true;
		this.drawer.classList.add("open");
		document.body.classList.add("fai-drawer-open");
		this.app.refresh_context(true);
		this.sync_button();
		setTimeout(() => this.app.$.input.focus({ preventScroll: true }), 120);
	}

	close() {
		if (!this.drawer) return;
		this.is_open = false;
		this.drawer.classList.remove("open");
		document.body.classList.remove("fai-drawer-open");
		this.sync_button();
	}

	toggle() {
		if (this.is_open) this.close();
		else this.open();
	}
}

function start() {
	if (start.done) return;
	start.done = true;
	try {
		new Launcher().init();
	} catch (e) {
		console.error("Fateh AI launcher failed", e); // eslint-disable-line no-console
	}
}

// app_include_js runs before frappe.Application is built; if we are late, start right away.
if (frappe.app) start();
else $(document).on("app_ready", start);
