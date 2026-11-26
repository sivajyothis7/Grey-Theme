// Copyright (c) 2026, Enfono Technologies and contributors
// For license information, please see license.txt
//
// Rendering helpers for Fateh AI: markdown -> sanitised DOM, ```chart blocks -> frappe.Chart,
// interactive result tables, inline SVG icons.
//
// Model output is untrusted (it can echo text from documents), so everything goes through a
// whitelist sanitiser and is inserted as DOM nodes. frappe.markdown() only sanitises on recent
// v15 builds; older benches return raw showdown HTML, so we never rely on it. Images are dropped
// entirely: a markdown image is a request to an arbitrary host and can leak data in its URL.

const ALLOWED_TAGS = new Set([
	"p", "br", "strong", "b", "em", "i", "u", "s", "del", "strike", "code", "pre", "blockquote",
	"ul", "ol", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table", "thead", "tbody", "tfoot",
	"tr", "th", "td", "a", "hr", "span", "div", "sup", "sub", "kbd",
]);
const DROP_WITH_CONTENT = new Set([
	"script", "style", "iframe", "object", "embed", "svg", "math", "template", "img", "video",
	"audio", "form", "input", "textarea", "select", "button", "link", "meta", "base", "noscript",
]);
const SAFE_ALIGN = /^text-align:\s*(left|right|center);?$/i;

// Parse an HTML string into a detached fragment. DOMParser documents are inert: scripts do not
// run and resources do not load while we sanitise.
function parse(html) {
	const doc = new DOMParser().parseFromString(`<!doctype html><body>${html}</body>`, "text/html");
	const frag = document.createDocumentFragment();
	frag.append(...doc.body.childNodes);
	return frag;
}

// Trusted static template (our own markup, with every dynamic value already escaped).
export function tpl(html) {
	return parse(html);
}

export function is_safe_href(href) {
	const h = String(href || "").trim();
	if (!h || h.startsWith("//")) return false;
	if (h.startsWith("/") || h.startsWith("#")) return true;
	return /^https?:\/\//i.test(h);
}

function clean_tree(node) {
	for (const el of [...node.children]) {
		const tag = el.tagName.toLowerCase();
		if (DROP_WITH_CONTENT.has(tag)) {
			el.remove();
			continue;
		}
		clean_tree(el);
		if (!ALLOWED_TAGS.has(tag)) {
			el.replaceWith(...el.childNodes);
			continue;
		}
		for (const attr of [...el.attributes]) {
			const name = attr.name.toLowerCase();
			const value = attr.value;
			const keep =
				(tag === "a" && name === "href" && is_safe_href(value)) ||
				(tag === "code" && name === "class" && /^[\w\s-]+$/.test(value)) ||
				((tag === "th" || tag === "td") && name === "style" && SAFE_ALIGN.test(value)) ||
				((tag === "th" || tag === "td") && name === "align" && /^(left|right|center)$/i.test(value));
			if (!keep) el.removeAttribute(attr.name);
		}
		if (tag === "a") {
			const href = el.getAttribute("href") || "";
			if (href === "/app" || href.startsWith("/app/")) {
				el.setAttribute("data-fai-route", href);
			} else if (href && !href.startsWith("#")) {
				el.setAttribute("target", "_blank");
				el.setAttribute("rel", "noopener noreferrer nofollow");
			}
		}
	}
}

// Untrusted HTML -> sanitised fragment.
export function sanitize(html) {
	const holder = document.createElement("div");
	holder.append(parse(html));
	clean_tree(holder);
	const out = document.createDocumentFragment();
	out.append(...holder.childNodes);
	return out;
}

function md_to_html(text) {
	if (frappe.markdown) return frappe.markdown(text);
	return `<p>${frappe.utils.escape_html(text).replace(/\n/g, "<br>")}</p>`;
}

// Hide a ```chart fence that is still streaming in, so raw JSON never flashes on screen.
function split_open_chart(text) {
	const fences = [...text.matchAll(/^```(\w*)\s*$/gm)];
	if (fences.length % 2 === 1) {
		const last = fences[fences.length - 1];
		if (last[1] === "chart") return { text: text.slice(0, last.index), pending_chart: true };
	}
	return { text, pending_chart: false };
}

// Markdown text -> sanitised fragment.
export function render_markdown(text, { streaming = false } = {}) {
	let pending_chart = false;
	text = text || "";
	if (streaming) ({ text, pending_chart } = split_open_chart(text));
	const frag = sanitize(md_to_html(text));
	if (pending_chart) {
		const p = document.createElement("div");
		p.className = "fai-chart-pending";
		p.textContent = __("Preparing chart…");
		frag.append(p);
	}
	return frag;
}

// --------------------------------------------------------------------------- charts

const CHART_TYPES = new Set(["bar", "line", "pie", "donut", "percentage"]);
// teal / slate family that matches the Grey Theme accent, then warm contrasts
const CHART_COLORS = ["#0f8a8f", "#5b6b82", "#38b2ac", "#a3b1c2", "#e0a43b", "#8b6fd6", "#e06c75", "#4c9be8"];

export function parse_chart(code) {
	let spec;
	try {
		spec = JSON.parse(code);
	} catch (e) {
		return null;
	}
	if (!spec || !Array.isArray(spec.labels) || !Array.isArray(spec.datasets) || !spec.datasets.length) return null;
	const labels = spec.labels.slice(0, 60).map((l) => String(l));
	const datasets = spec.datasets.slice(0, 6).map((d, i) => ({
		name: String((d && (d.name || d.label)) || `${__("Series")} ${i + 1}`),
		values: ((d && (d.values || d.data)) || []).slice(0, labels.length).map((v) => Number(v) || 0),
	}));
	let type = String(spec.type || "bar").toLowerCase();
	if (!CHART_TYPES.has(type)) type = "bar";
	return { type, title: spec.title ? String(spec.title) : "", labels, datasets };
}

function nice_number(n) {
	return Number(n).toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function render_charts(root) {
	root.querySelectorAll("pre > code").forEach((code) => {
		if (!/(^|\s)(language-)?chart(\s|$)/.test(code.className || "")) return;
		const spec = parse_chart(code.textContent);
		if (!spec) return; // leave the code block visible so the data is still readable
		const box = document.createElement("div");
		box.className = "fai-chart";
		const holder = document.createElement("div");
		box.append(holder);
		code.parentElement.replaceWith(box);
		try {
			new frappe.Chart(holder, {
				title: spec.title,
				type: spec.type,
				height: 240,
				data: { labels: spec.labels, datasets: spec.datasets },
				colors: CHART_COLORS,
				axisOptions: { xIsSeries: spec.type === "line" ? 1 : 0, shortenYAxisNumbers: 1 },
				tooltipOptions: { formatTooltipY: (d) => (typeof d === "number" ? nice_number(d) : d) },
				truncateLegends: 1,
			});
		} catch (e) {
			box.textContent = __("Could not draw this chart.");
		}
	});
}

// --------------------------------------------------------------------------- tables

export function table_to_rows(table) {
	return [...table.querySelectorAll("tr")].map((tr) => [...tr.querySelectorAll("th,td")].map((c) => c.innerText.trim()));
}

export function rows_to_csv(rows) {
	return rows
		.map((r) =>
			r
				.map((v) => {
					const s = v === null || v === undefined ? "" : String(v);
					return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
				})
				.join(",")
		)
		.join("\r\n");
}

export function download_csv(rows, filename) {
	// UTF-8 BOM so Excel opens Arabic text correctly
	const blob = new Blob(["﻿" + rows_to_csv(rows)], { type: "text/csv;charset=utf-8" });
	const url = URL.createObjectURL(blob);
	const a = document.createElement("a");
	a.href = url;
	a.download = (filename || "fateh-ai").replace(/[^\w\- ]+/g, "").slice(0, 60) + ".csv";
	document.body.append(a);
	a.click();
	setTimeout(() => {
		URL.revokeObjectURL(url);
		a.remove();
	}, 500);
}

export function copy_text(text) {
	if (navigator.clipboard && window.isSecureContext) {
		return navigator.clipboard
			.writeText(text)
			.then(() => frappe.show_alert({ message: __("Copied"), indicator: "green" }, 2));
	}
	frappe.utils.copy_to_clipboard(text);
	return Promise.resolve();
}

function sort_table(table, col, th) {
	const tbody = table.tBodies[0];
	if (!tbody) return;
	const dir = th.dataset.sort === "asc" ? "desc" : "asc";
	table.querySelectorAll("th").forEach((h) => delete h.dataset.sort);
	th.dataset.sort = dir;
	const num = (s) => {
		const n = parseFloat(String(s).replace(/[^\d.\-]/g, ""));
		return isNaN(n) ? null : n;
	};
	const rows = [...tbody.rows];
	rows.sort((a, b) => {
		const x = a.cells[col] ? a.cells[col].innerText.trim() : "";
		const y = b.cells[col] ? b.cells[col].innerText.trim() : "";
		const nx = num(x);
		const ny = num(y);
		const cmp = nx !== null && ny !== null ? nx - ny : x.localeCompare(y);
		return dir === "asc" ? cmp : -cmp;
	});
	rows.forEach((r) => tbody.append(r));
}

const NUMERIC_CELL = /^[-+(]?[^\d\s]{0,4}\s?[\d,.\s]+\)?%?(\s?[A-Z]{3})?$/u;

function button(icon_name, label, act) {
	const b = document.createElement("button");
	b.type = "button";
	b.className = "fai-chip-btn";
	b.dataset.act = act;
	b.append(icon_el(icon_name));
	const span = document.createElement("span");
	span.textContent = label;
	b.append(span);
	return b;
}

export function enhance_table(table, title) {
	if (table.closest(".fai-table")) return;
	const wrap = document.createElement("div");
	wrap.className = "fai-table";
	const scroller = document.createElement("div");
	scroller.className = "fai-table-scroll";
	const bar = document.createElement("div");
	bar.className = "fai-table-bar";
	bar.append(button("copy", __("Copy"), "copy"), button("download", __("CSV"), "csv"));
	table.replaceWith(wrap);
	scroller.append(table);
	wrap.append(scroller, bar);
	bar.addEventListener("click", (e) => {
		const btn = e.target.closest("button");
		if (!btn) return;
		const rows = table_to_rows(table);
		if (btn.dataset.act === "copy") copy_text(rows.map((r) => r.join("\t")).join("\n"));
		else download_csv(rows, title || "fateh-ai-table");
	});
	table.querySelectorAll("thead th").forEach((th, i) => {
		th.classList.add("fai-sortable");
		th.title = __("Sort");
		th.addEventListener("click", () => sort_table(table, i, th));
	});
	const body_rows = [...(table.tBodies[0] ? table.tBodies[0].rows : [])];
	if (!body_rows.length) return;
	const ncols = body_rows[0].cells.length;
	for (let c = 0; c < ncols; c++) {
		const numeric = body_rows.every((r) => {
			const t = r.cells[c] ? r.cells[c].innerText.trim() : "";
			return t === "" || NUMERIC_CELL.test(t);
		});
		if (numeric) table.querySelectorAll(`tr > :nth-child(${c + 1})`).forEach((cell) => cell.classList.add("fai-num"));
	}
}

function pretty_column(name) {
	const text = String(name).replace(/__/g, " · ").replace(/_/g, " ").trim();
	return text.charAt(0).toUpperCase() + text.slice(1);
}

export function build_preview_table(preview) {
	const frag = document.createDocumentFragment();
	if (!preview || !preview.columns || !preview.columns.length) return frag;
	const table = document.createElement("table");
	const hr = table.createTHead().insertRow();
	preview.columns.forEach((c) => {
		const th = document.createElement("th");
		th.textContent = pretty_column(c);
		th.title = String(c);
		hr.append(th);
	});
	const tbody = table.createTBody();
	(preview.rows || []).forEach((r) => {
		const tr = tbody.insertRow();
		r.forEach((v) => {
			tr.insertCell().textContent = v === null || v === undefined ? "" : String(v);
		});
	});
	frag.append(table);
	const shown = (preview.rows || []).length;
	if (preview.total && preview.total > shown) {
		const note = document.createElement("div");
		note.className = "fai-muted fai-small";
		note.textContent = __("Showing {0} of {1} rows", [shown, preview.total]);
		frag.append(note);
	}
	return frag;
}

export function enhance(root, { title } = {}) {
	render_charts(root);
	root.querySelectorAll("table").forEach((t) => enhance_table(t, title));
	root.querySelectorAll("pre").forEach((pre) => {
		const code = pre.querySelector("code");
		if (!code || pre.querySelector(".fai-copy-code")) return;
		const btn = document.createElement("button");
		btn.type = "button";
		btn.className = "fai-copy-code";
		btn.title = __("Copy");
		btn.append(icon_el("copy"));
		btn.addEventListener("click", () => copy_text(code.innerText));
		pre.append(btn);
	});
}

// Route /app/... links through the desk router instead of a full page load.
export function route_link(href) {
	const url = new URL(href, window.location.origin);
	const parts = url.pathname
		.replace(/^\/app\/?/, "")
		.split("/")
		.filter(Boolean)
		.map((p) => decodeURIComponent(p));
	const query = Object.fromEntries(url.searchParams.entries());
	if (!parts.length) return frappe.set_route("");
	if (Object.keys(query).length) return frappe.set_route(...parts, query);
	return frappe.set_route(...parts);
}

// --------------------------------------------------------------------------- icons (Lucide-style)

const PATHS = {
	sparkle:
		'<path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z"/><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/>',
	plus: '<path d="M12 5v14M5 12h14"/>',
	search: '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/>',
	history: '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l3 2"/>',
	x: '<path d="M18 6 6 18M6 6l12 12"/>',
	expand: '<path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7"/>',
	send: '<path d="M12 19V5M5 12l7-7 7 7"/>',
	stop: '<rect x="6" y="6" width="12" height="12" rx="2"/>',
	mic: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>',
	copy: '<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/>',
	retry: '<path d="M21 12a9 9 0 1 1-3-6.7L21 8"/><path d="M21 3v5h-5"/>',
	edit: '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>',
	pin: '<path d="M12 17v5M9 3h6l-1 7 4 3H6l4-3z"/>',
	trash: '<path d="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14"/>',
	download: '<path d="M12 3v12M7 10l5 5 5-5M5 21h14"/>',
	check: '<path d="M20 6 9 17l-5-5"/>',
	alert: '<circle cx="12" cy="12" r="9"/><path d="M12 8v4M12 16h.01"/>',
	lock: '<rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
	doc: '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6"/>',
	list: '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
	chart: '<path d="M3 3v18h18"/><path d="M7 15l4-4 3 3 5-6"/>',
	down: '<path d="M6 9l6 6 6-6"/>',
	tool: '<path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.6 2.6-2.4-.6-.6-2.4z"/>',
	settings:
		'<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1"/>',
};

export function icon(name, cls = "") {
	return `<svg class="fai-ico ${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${PATHS[name] || ""}</svg>`;
}

export function icon_el(name, cls = "") {
	return parse(icon(name, cls));
}
