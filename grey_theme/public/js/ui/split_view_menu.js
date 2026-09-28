// Copyright (c) 2026, Enfono Technologies and contributors
//
// Adds a "Split View" entry to the list view's views dropdown, and (optionally)
// keeps the Split View page out of the awesomebar. Everything here is a thin,
// idempotent runtime patch and is completely inert when the feature is off.

frappe.provide("frappe.views");
frappe.provide("frappe.search");
frappe.provide("grey_theme.split_view");

(function () {
	/**
	 * Read the settings published at boot. Never throws, never assumes the key
	 * is present, and is always read at call time so a stale include order
	 * cannot freeze an empty config in.
	 */
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

	// frappe/www/app.html assigns frappe.boot inline (line 54) before it renders the
	// app_include_js <script> tags (lines 69-70), so boot is already available here.
	// When it is and the feature is off, leave without touching a single prototype —
	// a disabled site must be byte-identical to stock Frappe.
	if (frappe.boot && !is_enabled()) {
		return;
	}

	/* --------------------------------------------------------- body class */

	function apply_body_class() {
		if (!document.body) {
			return;
		}
		document.body.classList.toggle("grey-ui-split", is_enabled());
	}

	$(document).ready(apply_body_class);

	/* ------------------------------------------------- list view menu entry */

	function patch_view_menu() {
		if (grey_theme.split_view.__menu_patched) {
			return;
		}
		if (
			!frappe.views ||
			!frappe.views.BaseList ||
			!frappe.views.BaseList.prototype ||
			typeof frappe.views.BaseList.prototype.setup_view_menu !== "function"
		) {
			return;
		}
		grey_theme.split_view.__menu_patched = true;

		const original_setup_view_menu = frappe.views.BaseList.prototype.setup_view_menu;

		frappe.views.BaseList.prototype.setup_view_menu = function () {
			original_setup_view_menu.call(this);

			if (!is_enabled()) {
				return;
			}

			// `views_menu` only exists when the view switcher is turned on, and
			// the entry must not be added twice to the same menu.
			if (!this.views_menu || this.views_menu.find('[data-view="SplitView"]').length) {
				return;
			}
			// this list view is the one already rendered inside the split screen
			if ($(this.parent).closest("#split-view-list").length) {
				return;
			}
			if (frappe.get_route()[0] === "split_view") {
				return;
			}

			const doctype = this.doctype || frappe.get_route()[1];
			if (is_excluded(doctype)) {
				return;
			}

			const $entry = $(`
				<li data-view="SplitView" class="dropdown-item">
					<a class="grey-link dropdown-item" href="#" onclick="return false;">
						<span class="menu-item-icon">
							<svg class="icon icon-sm" aria-hidden="true">
								<use href="#icon-dashboard"></use>
							</svg>
						</span>
						<span class="menu-item-label" data-label="Split View"></span>
					</a>
				</li>
			`);

			$entry.find(".menu-item-label").text(__("Split View"));
			$entry.appendTo(this.views_menu);

			$entry.on("click", function () {
				const target = doctype || frappe.get_route()[1];
				if (target) {
					frappe.set_route(["split_view", target]);
				}
				return false;
			});
		};
	}

	patch_view_menu();
	if (!grey_theme.split_view.__menu_patched) {
		// BaseList was not defined yet - try again once the desk is up.
		$(document).ready(patch_view_menu);
	}

	/* ------------------------------------------------------- awesomebar filter */

	function hides_page_from_search(option) {
		const route = option && option.route;

		if (Array.isArray(route) && route[0] === "split_view") {
			return true;
		}
		if (typeof route === "string" && route.split("/")[0] === "split_view") {
			return true;
		}

		// Match on the ROUTE only. The app this ports from also substring-matched the
		// option text, which hides every unrelated record whose name happens to contain
		// "Split View" (a Customer, a File, a saved report). `route` is the only field
		// that actually identifies the page.
		//
		// Options are built by several helpers and not all of them set every field, so
		// coerce before matching rather than calling .includes() on undefined.
		const value = String((option && option.value) || "");
		return value === "split_view" || value.indexOf("#split_view/") !== -1;
	}

	function patch_awesome_bar() {
		if (grey_theme.split_view.__awesomebar_patched) {
			return;
		}
		if (!frappe.search || !frappe.search.AwesomeBar) {
			return;
		}
		grey_theme.split_view.__awesomebar_patched = true;

		// The class has to be replaced before the toolbar instantiates it, which
		// can happen before frappe.boot is populated - so the flag is checked on
		// every call rather than once at install time.
		const OriginalAwesomeBar = frappe.search.AwesomeBar;

		frappe.search.AwesomeBar = class SplitViewAwesomeBar extends OriginalAwesomeBar {
			build_options(txt) {
				const options = super.build_options(txt) || [];
				const cfg = get_config();

				if (!cfg.split_view || !cfg.split_view_hide_page_from_search) {
					return options;
				}

				return options.filter(function (option) {
					return !hides_page_from_search(option);
				});
			}
		};
	}

	patch_awesome_bar();
	if (!grey_theme.split_view.__awesomebar_patched) {
		$(document).ready(patch_awesome_bar);
	}
})();
