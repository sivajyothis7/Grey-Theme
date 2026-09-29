// Copyright (c) 2026, Enfono Technologies and contributors

frappe.provide("frappe.views");
frappe.provide("frappe.ui");
frappe.provide("grey_theme.split_view");

(function () {
	// A Page script is eval'd once per desk session, but guard anyway so a
	// re-eval (dev reload, double include) cannot double-wrap anything.
	if (grey_theme.split_view.__page_loaded) {
		return;
	}
	grey_theme.split_view.__page_loaded = true;

	const NS = ".grey_split_view";
	const DRAG_NS = ".grey_split_view_drag";
	const STORAGE_KEY = "grey_theme_split_view_list_width";

	const DEFAULT_LIST_WIDTH_PCT = 50;
	const DEFAULT_MIN_PANE_WIDTH = 280;
	const MAX_LIST_WIDTH_RATIO = 0.75;
	const LIST_PAGE_LENGTH = 20;

	// doctype -> { frm, $host }. One Form instance per doctype, reused across
	// row clicks; torn down when the split view switches to another doctype.
	let form_cache = {};

	let current_doctype = null;
	let render_timer = null;
	// the live ListView in the left pane, kept so it can be torn down on doctype switch
	let current_list_view = null;
	let router_hook_installed = false;
	let resize_hook_installed = false;
	let split_page = null;

	/* --------------------------------------------------------------- config */

	function get_config() {
		return (frappe.boot && frappe.boot.grey_theme_ui) || {};
	}

	function is_enabled() {
		return !!get_config().split_view;
	}

	function get_excluded_doctypes() {
		const list = get_config().split_view_excluded_doctypes;
		return Array.isArray(list) ? list : [];
	}

	function is_excluded(doctype) {
		return !!doctype && get_excluded_doctypes().indexOf(doctype) !== -1;
	}

	function get_min_pane_width() {
		const value = cint(get_config().split_view_min_pane_width);
		return value > 0 ? value : DEFAULT_MIN_PANE_WIDTH;
	}

	function get_default_list_width_pct() {
		let pct = cint(get_config().split_view_list_width_pct);
		if (!pct) {
			pct = DEFAULT_LIST_WIDTH_PCT;
		}
		return Math.min(Math.max(pct, 10), 90);
	}

	/* -------------------------------------------------------- width memory */

	function read_saved_width() {
		try {
			return window.localStorage.getItem(STORAGE_KEY);
		} catch (e) {
			return null;
		}
	}

	function write_saved_width(value) {
		try {
			window.localStorage.setItem(STORAGE_KEY, value);
		} catch (e) {
			// private window / storage blocked - width memory is a nicety only
		}
	}

	function clear_saved_width() {
		try {
			window.localStorage.removeItem(STORAGE_KEY);
		} catch (e) {
			// ignore
		}
	}

	/* ------------------------------------------------------------ page entry */

	frappe.pages["split_view"].on_page_load = function (wrapper) {
		split_page = frappe.ui.make_app_page({
			parent: wrapper,
			title: __("Split View"),
			single_column: true,
		});

		// Install the router hook only when the feature is on: it is permanent and
		// fires for every route change site-wide, so a disabled site must not get one
		// just because someone typed /app/split_view into the address bar.
		if (!is_enabled()) {
			render_disabled_state(split_page);
			return;
		}

		install_router_hook();

		document.body.classList.add("grey-ui-split");

		build_chrome(split_page);
		install_resize_hook();
		sync_to_route();
	};

	frappe.pages["split_view"].on_page_show = function () {
		if (!is_enabled()) {
			return;
		}
		document.body.classList.add("grey-ui-split");
		sync_to_route();
	};

	/* ----------------------------------------------------------- off states */

	/**
	 * Built from frappe's own `msg-box` markup so it still reads correctly when
	 * this app's (feature-gated) stylesheet is inert.
	 */
	function make_off_state(title, hint) {
		const $state = $(`
			<div class="split-view-off-state">
				<div class="msg-box no-border">
					<p class="off-state-title"></p>
					<p class="text-muted small off-state-hint"></p>
					<p class="off-state-action"></p>
				</div>
			</div>
		`);
		$state.find(".off-state-title").text(title);
		$state.find(".off-state-hint").text(hint);
		return $state;
	}

	function render_disabled_state(page) {
		page.body.empty();

		const $state = make_off_state(
			__("Split View is turned off"),
			__("Turn it on in {0} to use the side-by-side list and form screen.", [
				__("Grey Theme UI Settings"),
			])
		).appendTo(page.body);

		$("<button type='button' class='btn btn-default btn-sm'></button>")
			.text(__("Open {0}", [__("Grey Theme UI Settings")]))
			.on("click" + NS, function () {
				frappe.set_route("Form", "Grey Theme UI Settings");
			})
			.appendTo($state.find(".off-state-action"));
	}

	function render_excluded_state(doctype) {
		teardown_form_cache();
		reset_form_pane();
		reset_list_pane();
		current_doctype = null;

		const $list = $("#split-view-list");
		if (!$list.length) {
			return;
		}

		const $state = make_off_state(
			__("Split View is not available here"),
			__("{0} is excluded from Split View.", [__(doctype)])
		).appendTo($list);

		$("<button type='button' class='btn btn-default btn-sm'></button>")
			.text(__("Open the list instead"))
			.on("click" + NS, switch_to_list_view)
			.appendTo($state.find(".off-state-action"));

		set_pane_heights();
	}

	/* ----------------------------------------------------------------- chrome */

	function build_chrome(page) {
		page.body.closest(".page-body").addClass("full-width");
		page.custom_actions.removeClass("hide");
		$(frappe.render_template("splitviewactions", {})).appendTo(page.custom_actions);
		$(frappe.render_template("split_view", {})).appendTo(page.body);

		page.custom_actions.find("li").on("click" + NS, function () {
			switch_to_list_view();
			return false;
		});

		apply_config_to_css_vars();
		setup_resizable_pane();
		set_pane_heights();
	}

	function get_page_element() {
		return document.getElementById("page-split_view");
	}

	function apply_list_pane_width(value) {
		const el = get_page_element();
		if (el) {
			el.style.setProperty("--grey-split-list-width", value);
		}
	}

	function apply_config_to_css_vars() {
		const el = get_page_element();
		if (!el) {
			return;
		}

		const min_width = get_min_pane_width();
		el.style.setProperty("--grey-split-min-width", min_width + "px");

		const saved_px = cint(read_saved_width());
		if (saved_px >= min_width) {
			apply_list_pane_width(saved_px + "px");
		} else {
			reset_pane_width();
		}
	}

	function reset_pane_width() {
		clear_saved_width();
		apply_list_pane_width(get_default_list_width_pct() + "%");
	}

	function setup_resizable_pane() {
		const $list = $("#split-view-list");
		const $splitter = $(".grey-split-view-splitter");
		const $body = $(".split-view-body");

		if (!$list.length || !$splitter.length || !$body.length) {
			return;
		}

		$(".split-view-reset-pane")
			.off("click" + NS)
			.on("click" + NS, function (e) {
				e.preventDefault();
				e.stopPropagation();
				reset_pane_width();
			});

		$splitter.off("mousedown" + NS + " touchstart" + NS);
		$splitter.on("mousedown" + NS + " touchstart" + NS, function (e) {
			if ($(e.target).closest(".split-view-reset-pane").length) {
				return;
			}
			e.preventDefault();
			start_drag(e, $list, $body);
		});
	}

	function get_client_x(e) {
		if (typeof e.clientX === "number") {
			return e.clientX;
		}
		const touches = e.originalEvent && e.originalEvent.touches;
		return touches && touches.length ? touches[0].clientX : 0;
	}

	function start_drag(e, $list, $body) {
		const is_rtl = document.documentElement.dir === "rtl";
		const start_x = get_client_x(e);
		const start_width = $list.outerWidth();
		const min_width = get_min_pane_width();
		let moved = false;

		$("body").addClass("split-view-resizing");

		function on_move(ev) {
			// mirror the drag for right-to-left layouts
			const delta = is_rtl ? start_x - get_client_x(ev) : get_client_x(ev) - start_x;
			if (delta !== 0) {
				moved = true;
			}
			const max_width = Math.floor($body.width() * MAX_LIST_WIDTH_RATIO);
			let new_width = start_width + delta;
			new_width = Math.max(min_width, Math.min(new_width, Math.max(min_width, max_width)));
			apply_list_pane_width(new_width + "px");
		}

		function on_up() {
			$("body").removeClass("split-view-resizing");
			$(document).off(DRAG_NS);
			// A bare mousedown+mouseup on the splitter is not a resize. Persisting it
			// would pin the pane to a pixel width and permanently defeat the
			// percentage default (and the "reset to centre" button's saved state).
			if (moved) {
				write_saved_width(String($("#split-view-list").outerWidth()));
			}
		}

		$(document).off(DRAG_NS);
		$(document).on("mousemove" + DRAG_NS + " touchmove" + DRAG_NS, on_move);
		$(document).on("mouseup" + DRAG_NS + " touchend" + DRAG_NS, on_up);
	}

	function set_pane_heights() {
		const $panes = $(".split-view-body");
		if (!$panes.length || !$panes.is(":visible")) {
			return;
		}

		// Measure where the panes actually start instead of trusting the
		// --navbar-height custom property, which may be expressed in rem.
		const top = $panes.get(0).getBoundingClientRect().top;
		const available = Math.floor(window.innerHeight - top - 2);

		if (available < 200) {
			return;
		}

		$panes.css("height", available + "px");
		$(".split-view-list, .split-view-form").css("height", available + "px");
	}

	function install_resize_hook() {
		if (resize_hook_installed) {
			return;
		}
		resize_hook_installed = true;

		$(window).on(
			"resize" + NS,
			frappe.utils.throttle(function () {
				try {
					set_pane_heights();
				} catch (e) {
					// a resize tick must never break the desk
				}
			}, 200)
		);
	}

	/* ---------------------------------------------------------------- routing */

	function install_router_hook() {
		if (router_hook_installed) {
			return;
		}
		router_hook_installed = true;

		// Registered exactly once for the whole session. It runs on every route
		// change in the desk, so keep it cheap and exception-safe.
		frappe.router.on("change", function () {
			try {
				const on_split_route = frappe.get_route()[0] === "split_view";
				document.body.classList.toggle("split-view-active", on_split_route);
				if (on_split_route && is_enabled()) {
					sync_to_route();
				}
			} catch (e) {
				// swallow - a throw here would break desk navigation
			}
		});
	}

	function sync_to_route() {
		const route = frappe.get_route();
		if (route[0] !== "split_view") {
			return;
		}

		document.body.classList.add("split-view-active");

		const doctype = route[1];
		if (!doctype) {
			if (split_page) {
				split_page.set_title(__("Split View"));
			}
			return;
		}

		if (split_page) {
			split_page.set_title(__(doctype));
		}

		if (is_excluded(doctype)) {
			if (current_doctype !== null || !$("#split-view-list").children().length) {
				render_excluded_state(doctype);
			}
			return;
		}

		const needs_render =
			doctype !== current_doctype || !$("#split-view-list").children().length;

		if (!needs_render) {
			set_pane_heights();
			return;
		}

		schedule_list_render(doctype);
	}

	function switch_to_list_view() {
		const doctype = frappe.get_route()[1];
		if (doctype) {
			frappe.set_route("List", doctype, "List");
		}
	}

	/* -------------------------------------------------------------- list pane */

	function schedule_list_render(doctype) {
		clearTimeout(render_timer);
		render_timer = setTimeout(function () {
			render_list_view(doctype);
		}, 100);
	}

	function reset_list_pane() {
		// Emptying the DOM does not unregister what the ListView bound elsewhere:
		// setup_realtime_updates() calls frappe.realtime.doctype_subscribe(doctype)
		// (list_view.js:1482) and setup_drag_click() binds an un-namespaced
		// $(document).on("mouseup") (list_view.js:1347). Without this teardown, walking
		// Item -> Customer -> Sales Order leaves a live socket subscription and a
		// document-level handler behind for every doctype visited.
		if (current_list_view) {
			try {
				if (typeof current_list_view.disable_realtime_updates === "function") {
					current_list_view.disable_realtime_updates();
				}
			} catch (err) {
				// teardown must never block the next render
			}
			current_list_view = null;
		}

		const $list = $("#split-view-list");
		if (!$list.length) {
			return;
		}
		$list.off(NS);
		$list.off("click" + NS, ".list-row");
		$list.empty();
	}

	function render_list_view(doctype) {
		reset_list_pane();
		teardown_form_cache();
		reset_form_pane();
		current_doctype = doctype;

		frappe.model.with_doctype(doctype, function () {
			const $list = $("#split-view-list");
			// with_doctype needs a server round trip on first visit, so the user may
			// already have left. Checking route[1] alone is not enough: navigating from
			// split_view/Customer to List/Customer keeps route[1] and would build a
			// second, invisible ListView that then steals the global realtime handler
			// from the list the user is actually looking at.
			const route = frappe.get_route();
			if (!$list.length || route[0] !== "split_view" || route[1] !== doctype) {
				return;
			}

			// make_app_page stashes the Page object on the object it is handed,
			// and BaseList reads it back off `parent.page` - so hand the very
			// same jQuery object to both.
			const app_page = frappe.ui.make_app_page({
				parent: $list,
				title: __(doctype),
			});

			const list_view = new frappe.views.ListView({
				doctype: doctype,
				parent: app_page.parent,
			});

			// page_length is deliberately NOT a constructor option: BaseList.setup_defaults()
			// overwrites it unconditionally with `frappe.is_large_screen() ? 100 : 20`
			// (base_list.js:45-47), so the option would be silently discarded. The list
			// here lives in a half-width pane, and is_large_screen() measures the WINDOW,
			// so a desktop user would otherwise pull 100 rows into it. Set it right after
			// core's own defaults land.
			const original_setup_defaults = list_view.setup_defaults;
			list_view.setup_defaults = function () {
				const result = original_setup_defaults.apply(this, arguments);
				this.page_length = LIST_PAGE_LENGTH;
				return result;
			};

			// Core binds its own delegated row-click on `this.$result`
			// (list_view.js:1296), which is a DESCENDANT of #split-view-list — so it
			// always fires before our handler on the ancestor and calls
			// frappe.set_route(), navigating the whole desk off the Split View page for
			// any click that is not the subject anchor. Out-bubbling it is impossible;
			// neutralise it instead. Safe to assign here: the constructor's show() is
			// frappe.run_serially(), so setup_events() -> setup_list_click() is still
			// several promise ticks away.
			list_view.setup_list_click = function () {};

			current_list_view = list_view;

			// BaseList defines after_render() as a no-op, but a list view class
			// from another app may not - guard before wrapping it.
			const original_after_render =
				typeof list_view.after_render === "function"
					? list_view.after_render.bind(list_view)
					: function () {};

			list_view.after_render = function () {
				original_after_render();
				bind_list_row_click();
				tidy_panes();
				set_pane_heights();
				setup_resizable_pane();
			};

			// NOTE: do NOT call list_view.show() here. frappe v15's ListView
			// constructor (list_view.js:25-26) already calls this.show(), and a second
			// call re-runs the whole show_skeleton -> fetch_meta -> check_permissions
			// -> before_refresh -> refresh chain as a second interleaving sequence
			// (two list fetches, two skeletons). after_render assigned just above still
			// lands first, because run_serially defers its first task to a microtask.
		});
	}

	/**
	 * Only the subject link and the bare row body open the document in the
	 * right pane. The row checkbox, the like/comment icons and every other
	 * link inside the row keep their own behaviour.
	 */
	function should_ignore_row_click(event) {
		const $target = $(event.target);

		// Controls that own their click: the row checkbox, the like heart, the
		// filterable cells/indicator pills, and any dropdown.
		if (
			$target.closest(
				"input, select, textarea, label, button, " +
					".list-row-checkbox, .list-check-all, .select-like, " +
					".list-row-like, .like-action, .likes-count, .comment-count, " +
					".filterable, [data-filter], " +
					'[data-toggle="dropdown"], .dropdown-menu'
			).length
		) {
			return true;
		}

		const $anchor = $target.closest("a");
		if (!$anchor.length) {
			// bare row body - intercept
			return false;
		}

		const subject_link = $(event.currentTarget)
			.find(".list-subject a[data-name]")
			.get(0);

		// any other anchor in the row (assignment, tag, workflow link, ...)
		return $anchor.get(0) !== subject_link;
	}

	function bind_list_row_click() {
		$("#split-view-list")
			.off("click" + NS, ".list-row")
			.on("click" + NS, ".list-row", function (event) {
				if (should_ignore_row_click(event)) {
					return;
				}

				// Stop the desk router from navigating away. Deliberately not
				// stopImmediatePropagation() - that would kill sibling handlers.
				event.preventDefault();
				event.stopPropagation();

				const link = $(event.currentTarget).find(".list-subject a[data-name]").get(0);
				if (!link) {
					return;
				}

				const doctype = $(link).attr("data-doctype") || current_doctype;
				const docname = $(link).attr("data-name");
				if (doctype && docname) {
					load_form_view(doctype, docname);
				}
			});
	}

	function escape_attr_value(value) {
		if (window.CSS && typeof window.CSS.escape === "function") {
			return window.CSS.escape(value);
		}
		return String(value).replace(/"/g, '\\"');
	}

	function mark_selected_row(docname) {
		const $list = $("#split-view-list");
		$list.find(".list-row").removeClass("split-view-selected");
		$list
			.find('.list-subject a[data-name="' + escape_attr_value(docname) + '"]')
			.closest(".list-row")
			.addClass("split-view-selected");
	}

	/* -------------------------------------------------------------- form pane */

	function reset_form_pane() {
		const $form = $("#split-view-form");
		if (!$form.length) {
			return;
		}
		$form.children().not("#split-view-form-empty").remove();
		$form.removeClass("has-doc");
		$form.find("#split-view-form-empty").show();
	}

	function teardown_form_cache() {
		Object.keys(form_cache).forEach(function (doctype) {
			const entry = form_cache[doctype];
			if (entry && entry.$host) {
				entry.$host.remove();
			}
			delete form_cache[doctype];
		});
		form_cache = {};
	}

	/** Drop every cached Form except the one for `doctype`, plus any whose host
	 *  node is no longer attached to the form pane. */
	function prune_form_cache(doctype, $form) {
		const pane = $form.get(0);
		Object.keys(form_cache).forEach(function (cached) {
			const entry = form_cache[cached];
			const host = entry && entry.$host && entry.$host.get(0);
			const stale = cached !== doctype || !host || !$.contains(pane, host);
			if (stale) {
				if (entry && entry.$host) {
					entry.$host.remove();
				}
				delete form_cache[cached];
			}
		});
	}

	/**
	 * frappe.model.with_doc runs its callback even when the fetch failed, so the two
	 * guards core's own formview uses (formview.js:81-90) have to be repeated here.
	 * Without them a row click on a document the user cannot read, or one another user
	 * has just deleted, either throws a TypeError out of frm.refresh() or — via
	 * frappe.show_not_found() — navigates the whole desk off the Split View page.
	 * Show the failure inside the right pane instead and stay put.
	 */
	function doc_is_loadable($form, doctype, name, r) {
		let message = null;

		if (r && r["403"]) {
			message = __("You do not have permission to view this document.");
		} else if (!(locals[doctype] && locals[doctype][name])) {
			message = __("This document could not be loaded. It may have been deleted.");
		}

		if (!message) {
			return true;
		}

		$form.find(".split-view-form-message").remove();
		$('<div class="split-view-form-message text-muted text-center"></div>')
			.text(message)
			.appendTo($form);
		return false;
	}

	function load_form_view(doctype, docname) {
		const $form = $("#split-view-form");
		if (!$form.length) {
			return;
		}

		mark_selected_row(docname);
		prune_form_cache(doctype, $form);

		$form.addClass("has-doc");
		$form.find("#split-view-form-empty").hide();
		$form.find(".split-view-form-message").remove();

		const cached = form_cache[doctype];
		if (cached) {
			cached.$host.show();
			frappe.model.with_doc(doctype, docname, function (name, r) {
				if (frappe.get_route()[0] !== "split_view") {
					return;
				}
				if (!doc_is_loadable($form, doctype, name, r)) {
					cached.$host.hide();
					return;
				}
				cached.frm.refresh(docname);
				after_form_render();
			});
			return;
		}

		const $loading = $('<div class="split-view-form-loading text-muted text-center"></div>')
			.text(__("Loading..."))
			.appendTo($form);

		frappe.model.with_doc(doctype, docname, function (name, r) {
			$loading.remove();

			if (frappe.get_route()[0] !== "split_view") {
				return;
			}
			if (!doc_is_loadable($form, doctype, name, r)) {
				return;
			}

			const $host = $('<div class="split-view-form-host"></div>')
				.attr("data-doctype", doctype)
				.appendTo($form);

			// frappe.router.doctype_layout is never cleared when the current
			// route is a Page, so passing it here would apply a stale DocType
			// Layout left over from whatever form was open last.
			const frm = new frappe.ui.form.Form(doctype, $host, true, undefined);
			frm.refresh(docname);

			form_cache[doctype] = { frm: frm, $host: $host };
			after_form_render();
		});
	}

	function after_form_render() {
		window.requestAnimationFrame(function () {
			tidy_panes();
			set_pane_heights();
		});
	}

	function tidy_panes() {
		$("#split-view-list > .page-head").hide();
		$("#split-view-list .layout-side-section").hide();
		$("#split-view-form .layout-side-section").hide();
		$("#split-view-form .page-head .standard-actions .prev-doc").hide();
		$("#split-view-form .page-head .standard-actions .next-doc").hide();
	}
})();
