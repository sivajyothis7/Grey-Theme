// Copyright (c) 2026, Enfono Technologies and contributors
// For license information, please see license.txt
//
// Fateh AI chat component. Mounted full-page at /app/ai-chat and inside the desk drawer
// (launcher.js). Talks to grey_theme.fateh_ai.api and listens to the "fateh_ai" realtime event
// published by the background agent. All dynamic text is either escaped into our own templates
// or rendered through render.js's sanitiser — never inserted as raw HTML.

import {
	render_markdown,
	enhance,
	icon,
	icon_el,
	tpl,
	route_link,
	build_preview_table,
	copy_text,
	download_csv,
} from "./render";

const API = "grey_theme.fateh_ai.api.";
const EVENT = "fateh_ai";
const RENDER_EVERY_MS = 90;
const WATCHDOG_MS = 5000;
const SILENCE_MS = 20000;

const esc = (s) => frappe.utils.escape_html(s === null || s === undefined ? "" : String(s));

function call(method, args = {}, opts = {}) {
	return new Promise((resolve, reject) => {
		frappe.call({
			method: API + method,
			args,
			type: opts.type || "POST",
			freeze: false,
			callback: (r) => resolve(r.message),
			error: (r) => reject(r),
			always: opts.always,
		});
	});
}

function step_status_icon(status) {
	if (status === "Success") return icon_el("check", "fai-ok");
	if (status === "Denied") return icon_el("lock", "fai-warn");
	if (status === "Error") return icon_el("alert", "fai-err");
	const s = document.createElement("span");
	s.className = "fai-spinner";
	return s;
}

// --------------------------------------------------------------------------------------------
// One assistant answer: ordered text segments and tool-step groups.
// --------------------------------------------------------------------------------------------

class BotTurn {
	constructor(app, { run_id = null, live = false } = {}) {
		this.app = app;
		this.run_id = run_id;
		this.segments = []; // {el, text}
		this.cur = null;
		this.steps_el = null;
		this.steps = {};
		this.render_timer = null;
		this.done = false;

		this.el = document.createElement("div");
		this.el.className = "fai-msg fai-bot";
		this.el.append(tpl(`<div class="fai-avatar fai-avatar-sm">${icon("sparkle")}</div>`));
		this.body = document.createElement("div");
		this.body.className = "fai-bot-body";
		this.el.append(this.body);

		this.typing = tpl(
			`<div class="fai-typing"><span></span><span></span><span></span><em>${esc(__("Thinking…"))}</em></div>`
		).firstElementChild;
		if (live) this.body.append(this.typing);
	}

	set_typing(text) {
		if (this.done) return;
		const em = this.typing.querySelector("em");
		if (em) em.textContent = text || __("Thinking…");
		this.body.append(this.typing); // keep it last
	}

	hide_typing() {
		this.typing.remove();
	}

	append_text(t) {
		if (!t) return;
		this.hide_typing();
		if (!this.cur) {
			const el = document.createElement("div");
			el.className = "fai-md";
			this.body.append(el);
			this.cur = { el, text: "" };
			this.segments.push(this.cur);
			this.steps_el = null;
		}
		this.cur.text += t;
		if (!this.render_timer) {
			this.render_timer = setTimeout(() => {
				this.render_timer = null;
				if (this.cur) this.cur.el.replaceChildren(render_markdown(this.cur.text, { streaming: true }));
				this.app.autoscroll();
			}, RENDER_EVERY_MS);
		}
	}

	close_text_segment() {
		if (this.render_timer) {
			clearTimeout(this.render_timer);
			this.render_timer = null;
		}
		if (this.cur) {
			this.cur.el.replaceChildren(render_markdown(this.cur.text));
			enhance(this.cur.el, { title: this.app.title_for_export() });
		}
		this.cur = null;
	}

	add_text_final(text) {
		if (!text) return;
		const el = document.createElement("div");
		el.className = "fai-md";
		el.append(render_markdown(text));
		this.body.append(el);
		enhance(el, { title: this.app.title_for_export() });
		this.segments.push({ el, text });
		this.steps_el = null;
	}

	ensure_steps_el() {
		if (!this.steps_el) {
			this.steps_el = document.createElement("div");
			this.steps_el.className = "fai-steps";
			this.body.append(this.steps_el);
		}
		return this.steps_el;
	}

	add_step(step, { final = false } = {}) {
		this.close_text_segment();
		const d = document.createElement("details");
		d.className = "fai-step";
		d.dataset.status = final ? step.status || "Success" : "running";
		const summary = document.createElement("summary");
		const ico = document.createElement("span");
		ico.className = "fai-step-ico";
		ico.append(step_status_icon(final ? step.status : null));
		const label = document.createElement("span");
		label.className = "fai-step-label";
		label.textContent = step.label || step.name;
		const meta = document.createElement("span");
		meta.className = "fai-step-meta";
		summary.append(ico, label, meta);
		d.append(summary);

		const body = document.createElement("div");
		body.className = "fai-step-body";
		d.append(body);
		const args = step.args && Object.keys(step.args).length ? JSON.stringify(step.args, null, 2) : "";
		if (args) {
			const pre = document.createElement("pre");
			pre.className = "fai-step-args";
			pre.textContent = args;
			body.append(pre);
		}
		this.ensure_steps_el().append(d);
		this.steps[step.id] = { el: d, ico, meta, body, step };
		if (final) this.update_step(step);
		else this.set_typing(__("{0}…", [step.label || step.name]));
		this.app.autoscroll();
	}

	update_step(ev) {
		const s = this.steps[ev.id];
		if (!s) return;
		s.el.dataset.status = ev.status;
		s.ico.replaceChildren(step_status_icon(ev.status));
		const bits = [];
		if (ev.status === "Success" && ev.row_count !== undefined && ev.row_count !== null) {
			bits.push(ev.row_count === 1 ? __("1 row") : __("{0} rows", [ev.row_count]));
		}
		if (ev.duration_ms) bits.push(ev.duration_ms >= 1000 ? `${(ev.duration_ms / 1000).toFixed(1)}s` : `${ev.duration_ms}ms`);
		if (ev.status === "Denied") bits.push(__("not permitted"));
		if (ev.status === "Error") bits.push(__("failed"));
		s.meta.textContent = bits.join(" · ");

		if (ev.error) {
			const err = document.createElement("div");
			err.className = "fai-step-error";
			err.textContent = ev.error;
			s.body.append(err);
		}
		if (ev.preview && ev.preview.columns && ev.preview.columns.length) {
			const wrap = document.createElement("div");
			wrap.className = "fai-step-preview";
			const scroll = document.createElement("div");
			scroll.className = "fai-table-scroll";
			scroll.append(build_preview_table(ev.preview));
			wrap.append(scroll);
			const csv = document.createElement("button");
			csv.type = "button";
			csv.className = "fai-chip-btn";
			csv.append(icon_el("download"), document.createTextNode(__("CSV")));
			csv.addEventListener("click", (e) => {
				e.preventDefault();
				download_csv([ev.preview.columns, ...(ev.preview.rows || [])], s.step.label || "fateh-ai");
			});
			wrap.append(csv);
			s.body.append(wrap);
		}
		if (!this.done) this.set_typing(__("Thinking…"));
	}

	error(message) {
		this.close_text_segment();
		this.hide_typing();
		const box = document.createElement("div");
		box.className = "fai-error";
		box.append(icon_el("alert"));
		const span = document.createElement("span");
		span.textContent = message || __("Something went wrong.");
		box.append(span);
		this.body.append(box);
	}

	note(message) {
		const n = document.createElement("div");
		n.className = "fai-note";
		n.textContent = message;
		this.body.append(n);
	}

	finish({ actions = true } = {}) {
		this.close_text_segment();
		this.hide_typing();
		this.done = true;
		Object.values(this.steps).forEach((s) => {
			if (s.el.dataset.status === "running") {
				s.el.dataset.status = "Error";
				s.ico.replaceChildren(step_status_icon("Error"));
			}
		});
		if (!actions || this.body.querySelector(".fai-actions")) return;
		const text = this.segments.map((s) => s.text).join("\n\n").trim();
		if (!text) return;
		const bar = document.createElement("div");
		bar.className = "fai-actions";
		const copy = document.createElement("button");
		copy.type = "button";
		copy.className = "fai-icon-btn";
		copy.title = __("Copy answer");
		copy.append(icon_el("copy"));
		copy.addEventListener("click", () => copy_text(text));
		bar.append(copy);
		this.body.append(bar);
	}
}

// --------------------------------------------------------------------------------------------
// The app
// --------------------------------------------------------------------------------------------

export class ChatApp {
	constructor({ parent, mode = "page", get_context = null, on_close = null, on_expand = null } = {}) {
		this.parent = parent && parent.jquery ? parent[0] : parent;
		this.mode = mode;
		this.get_context = get_context;
		this.on_close = on_close;
		this.on_expand = on_expand;

		this.info = null;
		this.conversation = null;
		this.conversation_title = "";
		this.conversations = [];
		this.run_id = null;
		this.sending = false;
		this.turn = null;
		this.early_events = [];
		this.last_event_at = 0;
		this.context_dismissed = false;
		this.last_question = "";

		this.make();
		this.bind();
		this.boot();
	}

	// ------------------------------------------------------------------ DOM
	make() {
		const name = esc((frappe.boot.fateh_ai && frappe.boot.fateh_ai.name) || "Fateh AI");
		const drawer = this.mode === "drawer";
		const root = tpl(`
			<div class="fai" data-mode="${drawer ? "drawer" : "page"}">
				<aside class="fai-side" aria-label="${esc(__("Conversations"))}">
					<div class="fai-side-head">
						<button type="button" class="fai-new-btn">${icon("plus")}<span>${esc(__("New chat"))}</span></button>
					</div>
					<label class="fai-search">${icon("search")}<input type="search" placeholder="${esc(__("Search chats"))}" aria-label="${esc(__("Search chats"))}"></label>
					<div class="fai-convs" role="list"></div>
				</aside>
				<section class="fai-main">
					<header class="fai-head">
						<button type="button" class="fai-icon-btn fai-toggle-side" title="${esc(__("History"))}">${icon("history")}</button>
						<div class="fai-avatar">${icon("sparkle")}</div>
						<div class="fai-head-text">
							<div class="fai-head-title">${name}</div>
							<div class="fai-head-sub"></div>
						</div>
						<div class="fai-head-actions">
							<button type="button" class="fai-icon-btn fai-new-icon" title="${esc(__("New chat"))}">${icon("plus")}</button>
							${drawer ? `<button type="button" class="fai-icon-btn fai-expand" title="${esc(__("Open full page"))}">${icon("expand")}</button>` : ""}
							${drawer ? `<button type="button" class="fai-icon-btn fai-close" title="${esc(__("Close"))} (Esc)">${icon("x")}</button>` : ""}
						</div>
					</header>
					<div class="fai-scroll">
						<div class="fai-thread" role="log" aria-live="polite"></div>
					</div>
					<button type="button" class="fai-jump" title="${esc(__("Jump to latest"))}">${icon("down")}</button>
					<footer class="fai-compose">
						<div class="fai-ctx"></div>
						<div class="fai-input">
							<textarea rows="1" placeholder="${esc(__("Ask about sales, stock, customers, reports…"))}" aria-label="${esc(__("Message"))}"></textarea>
							<button type="button" class="fai-icon-btn fai-mic" title="${esc(__("Speak"))}">${icon("mic")}</button>
							<button type="button" class="fai-send" title="${esc(__("Send"))}">${icon("send")}</button>
						</div>
						<div class="fai-foot">
							<span>${icon("lock")} ${esc(__("Read-only. Answers use your permissions and can be wrong — check important figures."))}</span>
							<span class="fai-usage"></span>
						</div>
					</footer>
				</section>
			</div>`).firstElementChild;

		if (frappe.utils.is_rtl && frappe.utils.is_rtl()) root.setAttribute("dir", "rtl");
		this.parent.append(root);
		this.root = root;
		const q = (sel) => root.querySelector(sel);
		this.$ = {
			side: q(".fai-side"),
			convs: q(".fai-convs"),
			search: q(".fai-search input"),
			scroll: q(".fai-scroll"),
			thread: q(".fai-thread"),
			jump: q(".fai-jump"),
			ctx: q(".fai-ctx"),
			input: q("textarea"),
			send: q(".fai-send"),
			mic: q(".fai-mic"),
			sub: q(".fai-head-sub"),
			usage: q(".fai-usage"),
			title: q(".fai-head-title"),
		};
		if (!(window.SpeechRecognition || window.webkitSpeechRecognition)) this.$.mic.remove();
		if (drawer || window.innerWidth < 900) root.classList.add("fai-side-collapsed");
	}

	bind() {
		const r = this.root;
		r.querySelector(".fai-new-btn").addEventListener("click", () => this.new_chat());
		r.querySelector(".fai-new-icon").addEventListener("click", () => this.new_chat());
		r.querySelector(".fai-toggle-side").addEventListener("click", () => r.classList.toggle("fai-side-collapsed"));
		const close = r.querySelector(".fai-close");
		if (close) close.addEventListener("click", () => this.on_close && this.on_close());
		const expand = r.querySelector(".fai-expand");
		if (expand)
			expand.addEventListener("click", () => {
				if (this.on_expand) this.on_expand(this.conversation);
			});

		this.$.send.addEventListener("click", () => (this.is_busy() ? this.stop() : this.send()));
		this.$.input.addEventListener("keydown", (e) => {
			if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
				e.preventDefault();
				if (!this.is_busy()) this.send();
			} else if (e.key === "ArrowUp" && !this.$.input.value && this.last_question) {
				e.preventDefault();
				this.set_input(this.last_question);
			} else if (e.key === "Escape" && this.mode === "drawer" && this.on_close) {
				this.on_close();
			}
		});
		this.$.input.addEventListener("input", () => this.autosize());
		this.$.mic.addEventListener("click", () => this.toggle_voice());

		let search_timer = null;
		this.$.search.addEventListener("input", () => {
			clearTimeout(search_timer);
			search_timer = setTimeout(() => this.load_conversations(), 250);
		});

		this.$.scroll.addEventListener("scroll", () => {
			const el = this.$.scroll;
			this.root.classList.toggle("fai-scrolled-up", el.scrollHeight - el.scrollTop - el.clientHeight > 160);
		});
		this.$.jump.addEventListener("click", () => this.scroll_bottom(true));

		// desk links inside answers route in-app
		r.addEventListener("click", (e) => {
			const a = e.target.closest("a[data-fai-route]");
			if (!a) return;
			e.preventDefault();
			route_link(a.getAttribute("data-fai-route"));
			if (this.mode === "drawer" && window.innerWidth < 900 && this.on_close) this.on_close();
		});

		this._rt = (data) => this.on_event(data);
		frappe.realtime.on(EVENT, this._rt);
		this._watchdog = setInterval(() => this.watchdog(), WATCHDOG_MS);
	}

	destroy() {
		try {
			frappe.realtime.off && frappe.realtime.off(EVENT, this._rt);
		} catch (e) {
			/* older builds */
		}
		clearInterval(this._watchdog);
		this.root.remove();
	}

	// ------------------------------------------------------------------ boot
	async boot() {
		try {
			this.info = await call("bootstrap", {}, { type: "GET" });
		} catch (e) {
			this.show_notice(__("Could not reach the assistant."), "alert");
			return;
		}
		const info = this.info;
		this.$.title.textContent = info.name || "Fateh AI";
		if (!info.allowed) {
			this.lock_composer();
			this.show_notice(info.reason || __("The assistant is not available."), "lock", info.is_system_manager);
			return;
		}
		if (!info.configured) {
			this.lock_composer();
			this.show_notice(
				info.is_system_manager
					? __("Choose a provider, API key and model in AI Settings to start.")
					: __("The assistant is not configured yet. Ask your System Manager."),
				"settings",
				info.is_system_manager
			);
			return;
		}
		this.$.sub.textContent = info.is_system_manager
			? [info.provider, info.model].filter(Boolean).join(" · ")
			: __("Read-only assistant");
		this.update_usage();
		this.load_conversations();
		this.show_empty();
		this.refresh_context();
		setTimeout(() => this.$.input.focus(), 50);
	}

	lock_composer() {
		this.$.input.disabled = true;
		this.$.send.disabled = true;
		this.root.classList.add("fai-locked");
	}

	show_notice(message, icon_name = "alert", settings_link = false) {
		const box = tpl(`
			<div class="fai-empty fai-notice">
				<div class="fai-avatar fai-avatar-lg">${icon(icon_name)}</div>
				<p>${esc(message)}</p>
				${settings_link ? `<button type="button" class="btn btn-primary btn-sm">${esc(__("Open AI Settings"))}</button>` : ""}
			</div>`).firstElementChild;
		const btn = box.querySelector("button");
		if (btn) btn.addEventListener("click", () => frappe.set_route("Form", "AI Settings"));
		this.$.thread.replaceChildren(box);
	}

	update_usage() {
		const info = this.info || {};
		if (info.daily_limit) {
			this.$.usage.textContent = __("{0} of {1} questions today", [info.used_today || 0, info.daily_limit]);
		} else {
			this.$.usage.textContent = "";
		}
	}

	// ------------------------------------------------------------------ context (drawer only)
	current_context() {
		if (this.mode !== "drawer" || this.context_dismissed || !this.get_context) return null;
		try {
			return this.get_context();
		} catch (e) {
			return null;
		}
	}

	refresh_context(route_changed = false) {
		if (route_changed) this.context_dismissed = false;
		const ctx = this.current_context();
		const box = this.$.ctx;
		box.replaceChildren();
		if (!ctx || !ctx.view || !ctx.doctype && !ctx.report) {
			box.hidden = true;
			if (this.is_empty_state) this.show_empty();
			return;
		}
		let icon_name = "doc";
		let label = "";
		if (ctx.view === "Form") {
			label = ctx.docname ? `${__(ctx.doctype)} · ${ctx.docname}` : __("New {0}", [__(ctx.doctype)]);
		} else if (ctx.view === "List") {
			icon_name = "list";
			label = __("{0} list", [__(ctx.doctype)]);
			if (ctx.selected && ctx.selected.length) label += ` · ${__("{0} selected", [ctx.selected.length])}`;
		} else if (ctx.view === "Report") {
			icon_name = "chart";
			label = __(ctx.report);
		}
		const pill = tpl(
			`<span class="fai-pill" title="${esc(__("The assistant can see which screen you are on"))}">${icon(icon_name)}<span></span><button type="button" title="${esc(__("Don't use this screen"))}">${icon("x")}</button></span>`
		).firstElementChild;
		pill.querySelector("span").textContent = label;
		pill.querySelector("button").addEventListener("click", () => {
			this.context_dismissed = true;
			this.refresh_context();
		});
		box.append(pill);
		box.hidden = false;
		if (this.is_empty_state) this.show_empty();
	}

	// ------------------------------------------------------------------ empty state
	suggestions() {
		const ctx = this.current_context();
		if (ctx && ctx.view === "Form" && ctx.docname) {
			const dt = __(ctx.doctype);
			return [
				__("Summarize this {0}", [dt]),
				__("Is anything unusual or missing on {0}?", [ctx.docname]),
				__("Show related documents for this {0}", [dt]),
				__("How does this compare with similar {0} records?", [dt]),
			];
		}
		if (ctx && ctx.view === "List") {
			const dt = __(ctx.doctype);
			return [
				ctx.selected && ctx.selected.length
					? __("Summarize the selected {0} records", [dt])
					: __("Summarize the {0} records in this list", [dt]),
				__("Count {0} by status", [dt]),
				__("Show the 10 most recent {0}", [dt]),
				__("Chart {0} created per month this year", [dt]),
			];
		}
		if (ctx && ctx.view === "Report") {
			return [
				__("Explain what the {0} report shows", [__(ctx.report)]),
				__("Run {0} with my current filters and summarize it", [__(ctx.report)]),
			];
		}
		return [
			__("Top 10 customers by sales this fiscal year"),
			__("Chart our sales by month this year"),
			__("Which customers have overdue invoices?"),
			__("Which items hold the most stock value?"),
			__("How many Sales Orders are still to be delivered?"),
			__("Which reports show profitability?"),
		];
	}

	show_empty() {
		if (!this.info || !this.info.allowed || !this.info.configured) return;
		if (this.conversation) return;
		this.is_empty_state = true;
		const first = this.info.user_first_name ? `, ${this.info.user_first_name}` : "";
		const box = tpl(`
			<div class="fai-empty">
				<div class="fai-avatar fai-avatar-lg">${icon("sparkle")}</div>
				<h3>${esc(__("Hi{0}! What would you like to know?", [first]))}</h3>
				<p class="fai-muted">${esc(__("I can look up records, total and compare figures, run reports and draw charts — using only the data you are allowed to see."))}</p>
				<div class="fai-suggest"></div>
			</div>`).firstElementChild;
		const grid = box.querySelector(".fai-suggest");
		this.suggestions().forEach((s) => {
			const b = document.createElement("button");
			b.type = "button";
			b.className = "fai-suggest-card";
			b.textContent = s;
			b.addEventListener("click", () => this.send(s));
			grid.append(b);
		});
		this.$.thread.replaceChildren(box);
	}

	// ------------------------------------------------------------------ conversations list
	async load_conversations() {
		if (!this.info || !this.info.allowed) return;
		try {
			this.conversations = (await call("list_conversations", { search: this.$.search.value || "" }, { type: "GET" })) || [];
		} catch (e) {
			this.conversations = [];
		}
		this.render_conversations();
	}

	render_conversations() {
		const box = this.$.convs;
		box.replaceChildren();
		if (!this.conversations.length) {
			const empty = document.createElement("div");
			empty.className = "fai-muted fai-small fai-convs-empty";
			empty.textContent = this.$.search.value ? __("No chats match.") : __("Your chats will appear here.");
			box.append(empty);
			return;
		}
		const today = frappe.datetime.get_today();
		const yesterday = frappe.datetime.add_days(today, -1);
		const week = frappe.datetime.add_days(today, -7);
		const groups = [];
		const group_of = (c) => {
			if (c.pinned) return __("Pinned");
			const d = (c.last_message_at || "").slice(0, 10);
			if (d === today) return __("Today");
			if (d === yesterday) return __("Yesterday");
			if (d >= week) return __("Previous 7 days");
			return __("Older");
		};
		this.conversations.forEach((c) => {
			const g = group_of(c);
			let group = groups.find((x) => x.label === g);
			if (!group) groups.push((group = { label: g, items: [] }));
			group.items.push(c);
		});
		groups.forEach((g) => {
			const h = document.createElement("div");
			h.className = "fai-group";
			h.textContent = g.label;
			box.append(h);
			g.items.forEach((c) => box.append(this.conversation_item(c)));
		});
	}

	conversation_item(c) {
		const item = tpl(`
			<div class="fai-conv" role="listitem" tabindex="0">
				<span class="fai-conv-title"></span>
				<span class="fai-conv-acts">
					<button type="button" data-act="pin" title="${esc(c.pinned ? __("Unpin") : __("Pin"))}">${icon("pin")}</button>
					<button type="button" data-act="rename" title="${esc(__("Rename"))}">${icon("edit")}</button>
					<button type="button" data-act="delete" title="${esc(__("Delete"))}">${icon("trash")}</button>
				</span>
			</div>`).firstElementChild;
		item.querySelector(".fai-conv-title").textContent = c.title || __("Untitled");
		item.classList.toggle("active", c.name === this.conversation);
		item.classList.toggle("pinned", !!c.pinned);
		item.addEventListener("click", (e) => {
			const btn = e.target.closest("button[data-act]");
			if (btn) {
				e.stopPropagation();
				this.conversation_action(btn.dataset.act, c);
				return;
			}
			this.open(c.name);
		});
		item.addEventListener("keydown", (e) => {
			if (e.key === "Enter") this.open(c.name);
		});
		return item;
	}

	async conversation_action(act, c) {
		if (act === "pin") {
			await call("pin_conversation", { name: c.name, pinned: c.pinned ? 0 : 1 });
			this.load_conversations();
		} else if (act === "rename") {
			frappe.prompt(
				{ fieldname: "title", fieldtype: "Data", label: __("Title"), default: c.title, reqd: 1 },
				async (v) => {
					await call("rename_conversation", { name: c.name, title: v.title });
					if (c.name === this.conversation) this.conversation_title = v.title;
					this.load_conversations();
				},
				__("Rename chat"),
				__("Save")
			);
		} else if (act === "delete") {
			frappe.confirm(__("Delete this chat? This cannot be undone."), async () => {
				await call("delete_conversation", { name: c.name });
				if (c.name === this.conversation) this.new_chat();
				this.load_conversations();
			});
		}
	}

	// ------------------------------------------------------------------ open / new
	new_chat() {
		if (this.is_busy()) return;
		this.conversation = null;
		this.conversation_title = "";
		this.turn = null;
		this.render_conversations();
		this.show_empty();
		this.$.input.focus();
		if (this.mode === "page" && window.innerWidth < 900) this.root.classList.add("fai-side-collapsed");
	}

	async open(name) {
		if (this.is_busy() && name !== this.conversation) {
			frappe.show_alert({ message: __("Wait for the current answer or press Stop."), indicator: "orange" });
			return;
		}
		let data;
		try {
			data = await call("get_conversation", { name }, { type: "GET" });
		} catch (e) {
			return;
		}
		this.conversation = data.name;
		this.conversation_title = data.title;
		this.is_empty_state = false;
		this.render_messages(data.messages || []);
		this.render_conversations();
		if (data.running) {
			this.run_id = data.running;
			this.turn = new BotTurn(this, { run_id: data.running, live: true });
			this.$.thread.append(this.turn.el);
			this.set_busy(true);
		}
		if (window.innerWidth < 900) this.root.classList.add("fai-side-collapsed");
		this.scroll_bottom(true);
	}

	render_messages(messages) {
		this.$.thread.replaceChildren();
		let turn = null;
		messages.forEach((m) => {
			if (m.role === "user") {
				turn = null;
				this.add_user_bubble(m.content);
				this.last_question = m.content;
				return;
			}
			if (!turn || turn.run_id !== m.run_id) {
				if (turn) turn.finish();
				turn = new BotTurn(this, { run_id: m.run_id });
				this.$.thread.append(turn.el);
			}
			if (m.is_error) {
				turn.error(m.content);
			} else {
				turn.add_text_final(m.content);
			}
			(m.steps || []).forEach((s) => turn.add_step(s, { final: true }));
		});
		if (turn) turn.finish();
	}

	add_user_bubble(text) {
		const el = tpl(`<div class="fai-msg fai-user"><div class="fai-bubble"></div></div>`).firstElementChild;
		el.querySelector(".fai-bubble").textContent = text;
		this.$.thread.append(el);
		return el;
	}

	// ------------------------------------------------------------------ send / stop
	is_busy() {
		return this.sending || !!this.run_id;
	}

	set_busy(busy) {
		this.root.classList.toggle("fai-busy", busy);
		this.$.send.replaceChildren(icon_el(busy ? "stop" : "send"));
		this.$.send.title = busy ? __("Stop") : __("Send");
		if (!busy) {
			this.sending = false;
			this.run_id = null;
		}
	}

	set_input(text) {
		this.$.input.value = text;
		this.autosize();
		this.$.input.focus();
	}

	autosize() {
		const t = this.$.input;
		t.style.height = "auto";
		t.style.height = Math.min(t.scrollHeight, 200) + "px";
	}

	async send(text) {
		if (this.is_busy() || !this.info || !this.info.configured) return;
		text = (text === undefined ? this.$.input.value : text).trim();
		if (!text) return;

		if (this.is_empty_state) {
			this.$.thread.replaceChildren();
			this.is_empty_state = false;
		}
		this.last_question = text;
		this.set_input("");
		this.add_user_bubble(text);
		this.turn = new BotTurn(this, { live: true });
		this.$.thread.append(this.turn.el);
		this.scroll_bottom(true);

		this.sending = true;
		this.early_events = [];
		this.set_busy(true);
		this.last_event_at = Date.now();

		const ctx = this.current_context();
		let res;
		try {
			res = await call("send_message", {
				message: text,
				conversation: this.conversation || "",
				context: ctx ? JSON.stringify(ctx) : "",
			});
		} catch (e) {
			this.turn.error(__("Your question could not be sent."));
			this.turn.finish({ actions: false });
			this.set_busy(false);
			return;
		}
		const is_new = !this.conversation;
		this.conversation = res.conversation;
		this.run_id = res.run_id;
		this.turn.run_id = res.run_id;
		this.sending = false;
		if (is_new) {
			this.conversation_title = text.slice(0, 80);
			this.load_conversations();
		}
		if (this.info) this.info.used_today = (this.info.used_today || 0) + 1;
		this.update_usage();
		const early = this.early_events.filter((ev) => ev.run_id === res.run_id);
		this.early_events = [];
		early.forEach((ev) => this.on_event(ev));
	}

	async stop() {
		if (!this.run_id) return;
		try {
			await call("stop", { run_id: this.run_id });
		} catch (e) {
			/* ignore */
		}
		if (this.turn) this.turn.set_typing(__("Stopping…"));
	}

	retry() {
		if (this.last_question) this.send(this.last_question);
	}

	// ------------------------------------------------------------------ realtime
	on_event(ev) {
		if (!ev || !ev.run_id) return;
		if (this.sending && !this.run_id) {
			this.early_events.push(ev);
			return;
		}
		if (ev.run_id !== this.run_id || !this.turn) return;
		this.last_event_at = Date.now();
		const turn = this.turn;
		switch (ev.type) {
			case "delta":
				turn.append_text(ev.text);
				this.autoscroll();
				break;
			case "tool_start":
				turn.add_step(ev);
				break;
			case "tool_end":
				turn.update_step(ev);
				break;
			case "done":
				this.finish_turn();
				break;
			case "stopped":
				turn.note(__("Stopped."));
				this.finish_turn();
				break;
			case "error":
				turn.error(ev.message);
				this.finish_turn(false);
				break;
		}
	}

	finish_turn(actions = true) {
		if (this.turn) {
			this.turn.finish({ actions });
			this.add_retry(this.turn);
		}
		this.turn = null;
		this.set_busy(false);
		this.autoscroll();
		this.load_conversations();
		this.$.input.focus();
	}

	add_retry(turn) {
		this.$.thread.querySelectorAll(".fai-retry").forEach((b) => b.remove());
		let bar = turn.body.querySelector(".fai-actions");
		if (!bar) {
			bar = document.createElement("div");
			bar.className = "fai-actions";
			turn.body.append(bar);
		}
		const b = document.createElement("button");
		b.type = "button";
		b.className = "fai-icon-btn fai-retry";
		b.title = __("Ask again");
		b.append(icon_el("retry"));
		b.addEventListener("click", () => this.retry());
		bar.append(b);
	}

	// Realtime is the fast path; if the socket is down we still finish by polling.
	async watchdog() {
		if (!this.run_id || !this.conversation || this.sending) return;
		if (Date.now() - this.last_event_at < SILENCE_MS) return;
		this.last_event_at = Date.now();
		let data;
		try {
			data = await call("get_conversation", { name: this.conversation }, { type: "GET" });
		} catch (e) {
			return;
		}
		if (!data.running) {
			this.turn = null;
			this.set_busy(false);
			this.render_messages(data.messages || []);
			this.scroll_bottom(true);
			this.load_conversations();
		}
	}

	// ------------------------------------------------------------------ misc
	title_for_export() {
		return this.conversation_title || "fateh-ai";
	}

	autoscroll() {
		const el = this.$.scroll;
		if (el.scrollHeight - el.scrollTop - el.clientHeight < 200) this.scroll_bottom();
	}

	scroll_bottom(force = false) {
		const el = this.$.scroll;
		requestAnimationFrame(() => {
			el.scrollTop = el.scrollHeight;
			if (force) this.root.classList.remove("fai-scrolled-up");
		});
	}

	toggle_voice() {
		const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
		if (!SR) return;
		if (this.recognition) {
			this.recognition.stop();
			return;
		}
		const rec = new SR();
		const lang = (frappe.boot.lang || "en").toLowerCase();
		rec.lang = lang.startsWith("ar") ? "ar-SA" : lang.includes("-") ? lang : `${lang}-${lang === "en" ? "US" : lang.toUpperCase()}`;
		rec.interimResults = true;
		rec.continuous = false;
		const base = this.$.input.value ? this.$.input.value + " " : "";
		rec.onresult = (e) => {
			const text = [...e.results].map((r) => r[0].transcript).join("");
			this.set_input(base + text);
		};
		rec.onend = () => {
			this.recognition = null;
			this.$.mic.classList.remove("fai-listening");
		};
		rec.onerror = rec.onend;
		this.recognition = rec;
		this.$.mic.classList.add("fai-listening");
		rec.start();
	}
}
