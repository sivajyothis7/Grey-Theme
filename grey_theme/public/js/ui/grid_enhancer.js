// Copyright (c) 2026, Enfono Technologies and contributors
// For license information, please see license.txt

/**
 * Grey Theme — Grid Enhancer
 *
 * Thin, idempotent RUNTIME PATCHES over whatever Frappe version is installed.
 * Nothing here forks frappe/public/js/frappe/form/grid*.js, so every upstream
 * fix (identity-based row matching, get_random_name(), grid_page_length meta
 * support, the CSV import cap, depends_on refresh, ...) is preserved.
 *
 * Features, all gated on frappe.boot.grey_theme_ui.grid_enhancer:
 *   a) a wider column budget than Frappe's hard cap of 11 col-units
 *   b) native horizontal scrolling of heading row + filter row + data rows
 *   c) native position:sticky pinned ("sticky") columns, picked in the grid's
 *      own Configure Columns dialog
 *
 * Reachability notes (Frappe v15):
 *   Grid and GridRow are ES-module default exports, so they are NOT available
 *   as frappe.ui.form.Grid / frappe.ui.form.GridRow. frappe.ui.form.ControlTable
 *   IS a global, and its make() constructs the Grid — so overriding ControlTable
 *   is the only supported way to reach the live prototypes.
 */

(function () {
	if (typeof frappe === "undefined" || !frappe.ui || !frappe.ui.form) return;

	const MODULE_FLAG = "__grey_theme_grid_enhancer__";
	const GRID_PROTO_FLAG = "__grey_grid_proto_patched__";
	const ROW_PROTO_FLAG = "__grey_grid_row_proto_patched__";

	// A second import must be a complete no-op.
	if (window[MODULE_FLAG]) return;

	const DEFAULT_MIN_COL_WIDTH = 100;
	const DEFAULT_COLUMN_LIMIT = 40;
	const DEFAULT_MAX_STICKY = 3;
	const STICKY_CLASS = "grey-sticky-col";

	// The widest `col-xs-N` class the stylesheet emits a width rule for. Keep this in
	// sync with the @for loop in grey_theme_grid.bundle.scss — a column wider than this
	// would render unsized and misalign the heading, filter and data rows.
	const MAX_COLUMN_WIDTH = 20;

	// Frappe's own budget: setup_visible_columns() stops at `total_colsize > 11`, which
	// is what keeps a stock grid inside one 12-unit bootstrap row. A grid at or under
	// this needs no help from us — see needs_wide_layout().
	const STOCK_COLUMN_CAP = 11;

	/* ---------------------------------------------------------------- config */

	function get_cfg() {
		return (frappe.boot && frappe.boot.grey_theme_ui) || {};
	}

	function enabled() {
		return !!get_cfg().grid_enhancer;
	}

	function sticky_enabled() {
		const cfg = get_cfg();
		return !!(cfg.grid_enhancer && cfg.grid_sticky_columns);
	}

	function column_limit() {
		const n = cint(get_cfg().grid_column_limit);
		return n > 0 ? n : DEFAULT_COLUMN_LIMIT;
	}

	function max_sticky() {
		const n = cint(get_cfg().grid_max_sticky_columns);
		return n > 0 ? n : DEFAULT_MAX_STICKY;
	}

	function min_col_width() {
		const n = cint(get_cfg().grid_min_column_width);
		return n > 0 ? n : DEFAULT_MIN_COL_WIDTH;
	}

	function is_rtl() {
		if (document.documentElement && document.documentElement.dir === "rtl") return true;
		return !!(frappe.utils && frappe.utils.is_rtl && frappe.utils.is_rtl());
	}

	function log_error(err) {
		// never let an enhancement failure escape into Frappe's own code paths
		console.error("[grey_theme] grid enhancer:", err);
	}

	/* ------------------------------------------------------------- patch glue */

	/** Run `after(return_value, arguments)` once the original has run. Return value preserved. */
	function wrap_after(obj, name, after) {
		const orig = obj[name];
		if (typeof orig !== "function") return;
		obj[name] = function () {
			const ret = orig.apply(this, arguments);
			try {
				after.call(this, ret, arguments);
			} catch (err) {
				log_error(err);
			}
			return ret;
		};
	}

	/** Run `before(arguments)` before the original runs. Return value preserved. */
	function wrap_before(obj, name, before) {
		const orig = obj[name];
		if (typeof orig !== "function") return;
		obj[name] = function () {
			try {
				before.call(this, arguments);
			} catch (err) {
				log_error(err);
			}
			return orig.apply(this, arguments);
		};
	}

	/* --------------------------------------------------------------- body/css */

	let body_flags_done = false;

	function apply_body_flags() {
		if (!enabled()) return;
		if (document.documentElement) {
			document.documentElement.style.setProperty(
				"--grey-grid-min-col-width",
				min_col_width() + "px"
			);
		}
		if (!document.body) return;
		document.body.classList.add("grey-ui-grid");
		body_flags_done = true;
	}

	/* ------------------------------------------------------- sticky bookkeeping */

	/**
	 * Recompute grid.grey_sticky_fieldnames from the saved GridView user settings.
	 * Only a contiguous run of sticky columns starting at the very first column can
	 * ever be pinned to the left edge, so the run is cut at the first non-sticky entry.
	 */
	function recompute_sticky_fieldnames(grid) {
		if (!grid) return;
		grid.grey_sticky_fieldnames = [];
		if (!sticky_enabled() || !grid.frm || !grid.doctype) return;

		const settings = frappe.get_user_settings(grid.frm.doctype, "GridView");
		const saved = settings && settings[grid.doctype];
		if (!saved || !saved.length) return;

		const limit = max_sticky();
		const picked = [];
		for (let i = 0; i < saved.length; i++) {
			const row = saved[i];
			if (!row || !row.fieldname) break;
			if (!row.sticky) break;
			picked.push(row.fieldname);
			if (picked.length >= limit) break;
		}
		grid.grey_sticky_fieldnames = picked;
	}

	/**
	 * Recompute sticky offsets for the heading row, the filter row and every data row.
	 * Fully idempotent; never throws for a detached or empty grid.
	 */
	function refresh_sticky(grid) {
		try {
			do_refresh_sticky(grid);
		} catch (err) {
			log_error(err);
		}
	}

	function do_refresh_sticky(grid) {
		if (!grid || !enabled()) return;
		if (!grid.grey_sticky_fieldnames) recompute_sticky_fieldnames(grid);

		// Re-evaluated on every refresh, not just at make(): Configure Columns can add
		// or remove columns and flip a grid between the stock and the wide layout.
		const host = (grid.form_grid && grid.form_grid[0]) || null;
		const container = host && host.closest(".form-grid-container");
		const wide = needs_wide_layout(grid);
		if (container) container.classList.toggle("grey-grid-wide", wide);

		const names = grid.grey_sticky_fieldnames || [];
		// Nothing overflows on a stock-width grid, so there is nothing to pin. Clearing
		// here also strips any offsets left behind by a grid that used to be wide.
		const pin = wide && sticky_enabled();
		const rtl = is_rtl();

		const rows = [];
		collect_row(grid.header_row, rows);
		collect_row(grid.header_search, rows);
		(grid.grid_rows || []).forEach(function (grid_row) {
			collect_row(grid_row, rows);
		});
		if (!rows.length) return;

		// --- phase 1: writes that do not depend on geometry (classes + resets)
		const plans = [];
		rows.forEach(function (row_el) {
			const cells = [];
			let run_open = true;

			for (let i = 0; i < row_el.children.length; i++) {
				const cell = row_el.children[i];
				if (!cell.classList || !cell.classList.contains("col")) continue;

				// Upstream's touchmove handler hand-rolls mobile scrolling by moving
				// .form-grid with style.left, and calls preventDefault() while doing it
				// — which would kill NATIVE touch scrolling. Drop that one handler only:
				// touchstart still primes the closure that the cell's click handler
				// (on_input_focus) reads on touch devices, and its style writes are
				// already neutralised by the !important rules in the stylesheet.
				if (cell.dataset.greyTouchFreed !== "1") {
					cell.dataset.greyTouchFreed = "1";
					$(cell).off("touchmove");
				}

				const is_handle =
					cell.classList.contains("row-check") || cell.classList.contains("row-index");
				const fieldname = cell.getAttribute("data-fieldname");

				let want = false;
				if (is_handle) {
					want = pin;
				} else if (pin && fieldname && names.indexOf(fieldname) > -1) {
					want = true;
				}
				// a sticky column after a non-sticky one cannot anchor to the left edge
				if (want && !run_open) want = false;
				if (!want) run_open = false;

				cell.classList.toggle(STICKY_CLASS, want);
				if (want) {
					cell.setAttribute("data-sticky-order", String(cells.length));
					cells.push(cell);
				} else {
					cell.removeAttribute("data-sticky-order");
					cell.style.left = "";
					cell.style.right = "";
				}
			}

			plans.push({ cells: cells });
		});

		// A grid inside an inactive tab pane or a collapsed section has no layout box,
		// so every offsetWidth reads 0 and we would write left:0 onto every pinned cell
		// — stacking them on top of each other once the tab is finally opened. Defer
		// instead, and recompute the first time the grid actually has geometry.
		if (!host || !host.offsetParent) {
			grid.grey_sticky_dirty = true;
			watch_for_layout(grid);
			return;
		}
		grid.grey_sticky_dirty = false;

		// --- phase 2: reads (one layout flush for the whole grid)
		plans.forEach(function (plan) {
			plan.widths = plan.cells.map(function (cell) {
				return cell.offsetWidth;
			});
		});

		// --- phase 3: writes
		plans.forEach(function (plan) {
			let offset = 0;
			plan.cells.forEach(function (cell, i) {
				if (rtl) {
					cell.style.right = offset + "px";
					cell.style.left = "";
				} else {
					cell.style.left = offset + "px";
					cell.style.right = "";
				}
				offset += plan.widths[i];
			});
		});

		pin_open_row_forms(grid);
	}

	/**
	 * The expanded row form (.form-in-grid) is a block child of .grid-row, which stays
	 * scrollport-width rather than max-content. `position: sticky` alone cannot offset
	 * it, because a sticky box is clamped to its containing block and it already fills
	 * that block exactly. Give it the scrollport's width explicitly so the sticky rule
	 * in the stylesheet has room to work and the open form stays in view while the row
	 * beside it is scrolled right.
	 */
	function pin_open_row_forms(grid) {
		const host = (grid.form_grid && grid.form_grid[0]) || null;
		if (!host) return;

		// upstream's Grid caches this.form_grid but NOT the container, so walk to it
		const container = host.closest(".form-grid-container");
		const width = (container && container.clientWidth) || host.clientWidth || 0;
		const forms = host.querySelectorAll(".form-in-grid");
		for (let i = 0; i < forms.length; i++) {
			forms[i].style.width = width ? width + "px" : "";
		}
	}

	/**
	 * One-shot IntersectionObserver for a grid that had no layout box when we last
	 * tried to place its pinned columns (inactive tab, collapsed section, hidden modal).
	 */
	function watch_for_layout(grid) {
		if (grid.grey_layout_watcher || typeof IntersectionObserver === "undefined") return;

		const host = (grid.form_grid && grid.form_grid[0]) || null;
		if (!host) return;

		grid.grey_layout_watcher = new IntersectionObserver(function (entries) {
			if (!entries.some((e) => e.isIntersecting)) return;
			grid.grey_layout_watcher.disconnect();
			grid.grey_layout_watcher = null;
			refresh_sticky(grid);
		});
		grid.grey_layout_watcher.observe(host);
	}

	function collect_row(grid_row, out) {
		if (!grid_row || !grid_row.row || !grid_row.row.length) return;
		const el = grid_row.row[0];
		if (!el || !el.isConnected) return;

		// make_search_column() does not stamp data-fieldname on its cell, but it does
		// register it in search_columns — backfill so the DOM pass can read it.
		if (grid_row.search_columns) {
			Object.keys(grid_row.search_columns).forEach(function (fieldname) {
				const $col = grid_row.search_columns[fieldname];
				if ($col && $col.length && !$col.attr("data-fieldname")) {
					$col.attr("data-fieldname", fieldname);
				}
			});
		}
		out.push(el);
	}

	/* ------------------------------------------------------ Grid.prototype patch */

	function patch_grid_prototype(proto) {
		if (!proto || proto[GRID_PROTO_FLAG]) return;
		Object.defineProperty(proto, GRID_PROTO_FLAG, { value: true, enumerable: false });

		wrap_after(proto, "make", function () {
			enhance_instance(this);
		});

		wrap_after(proto, "make_head", function () {
			if (this.header_row) {
				patch_grid_row_prototype(Object.getPrototypeOf(this.header_row));
			}
			refresh_sticky(this);
		});

		wrap_after(proto, "refresh", function () {
			refresh_sticky(this);
		});

		wrap_after(proto, "render_result_rows", function () {
			refresh_sticky(this);
		});

		wrap_after(proto, "setup_user_defined_columns", function () {
			recompute_sticky_fieldnames(this);
		});

		patch_setup_visible_columns(proto);
	}

	/**
	 * Upstream setup_visible_columns() stops mid-loop with
	 *     total_colsize += df.colsize; if (total_colsize > 11) return false;
	 * The early return also skips the width-redistribution loop below it, so
	 * this.visible_columns ends up as an exact PREFIX of the eligible-field list.
	 * Appending the remaining eligible fields in source order therefore reproduces
	 * exactly what a raised cap would have produced — and when the cap never fired,
	 * there is nothing left to append and this is a no-op.
	 */
	function patch_setup_visible_columns(proto) {
		const orig = proto.setup_visible_columns;
		if (typeof orig !== "function") return;

		proto.setup_visible_columns = function () {
			const already_built = !!(this.visible_columns && this.visible_columns.length > 0);
			const ret = orig.apply(this, arguments);
			if (!already_built && enabled()) {
				try {
					append_overflow_columns(this);
				} catch (err) {
					log_error(err);
				}
			}
			return ret;
		};
	}

	function append_overflow_columns(grid) {
		if (!grid || !grid.visible_columns) return;

		// Recomputed from scratch on every setup_visible_columns(): this is the single
		// source of truth for whether the wide layout is needed (see needs_wide_layout).
		grid.grey_appended_columns = 0;

		const limit = column_limit();
		if (limit <= STOCK_COLUMN_CAP) return;

		const use_user_columns = !!(grid.user_defined_columns && grid.user_defined_columns.length);
		const fields = use_user_columns
			? grid.user_defined_columns
			: grid.editable_fields || grid.docfields;
		if (!fields) return;

		const present = {};
		let total_colsize = 1;
		grid.visible_columns.forEach(function (col) {
			if (col && col[0] && col[0].fieldname) present[col[0].fieldname] = true;
			total_colsize += cint(col && col[1]);
		});

		// same predicate, same df resolution, same order as upstream
		for (const ci in fields) {
			const _df = fields[ci];
			if (!_df) continue;

			const df = use_user_columns ? _df : grid.fields_map[_df.fieldname];
			if (!df || df.hidden) continue;
			if (!(grid.editable_fields || df.in_list_view)) continue;
			if (!((grid.frm && grid.frm.get_perm(df.permlevel, "read")) || !grid.frm)) continue;
			if (frappe.model.layout_fields.includes(df.fieldtype)) continue;
			if (present[df.fieldname]) continue;

			if (df.columns) {
				df.colsize = df.columns;
			} else {
				grid.update_default_colsize(df);
			}

			// attach formatter on refresh (mirrors upstream)
			if (
				df.fieldtype == "Link" &&
				!df.formatter &&
				df.parent &&
				frappe.meta.docfield_map[df.parent]
			) {
				const docfield = frappe.meta.docfield_map[df.parent][df.fieldname];
				if (docfield && docfield.formatter) {
					df.formatter = docfield.formatter;
				}
			}

			total_colsize += df.colsize;
			if (total_colsize > limit) return;

			grid.visible_columns.push([df, df.colsize]);
			present[df.fieldname] = true;
			grid.grey_appended_columns += 1;
		}
		// deliberately no width-redistribution pass: upstream skips it too once the
		// cap has fired, and redistributing here would desync header/filter/data rows
	}

	/* --------------------------------------------------- GridRow.prototype patch */

	function patch_grid_row_prototype(proto) {
		if (!proto || proto[ROW_PROTO_FLAG]) return;
		Object.defineProperty(proto, ROW_PROTO_FLAG, { value: true, enumerable: false });

		wrap_after(proto, "make_column", function (ret, args) {
			mark_sticky_cell(this, ret, args[0]);
		});

		// not in the brief, but without it the filter row neither pins nor carries a
		// fieldname, and grid_enhancer's live misalignment bug would be reproduced
		wrap_after(proto, "make_search_column", function (ret, args) {
			mark_sticky_cell(this, ret, args[0]);
		});

		wrap_after(proto, "setup_columns_for_dialog", function () {
			stamp_dialog_sticky(this);
		});

		// patched here rather than on configure_dialog_for_columns_selector because
		// adding a field re-renders the list and would otherwise drop the checkboxes
		wrap_after(proto, "render_selected_columns", function () {
			inject_sticky_toggles(this);
		});

		patch_sort_columns(proto);
		patch_validate_columns_width(proto);

		// upstream saves this.selected_columns_for_grid verbatim, so a `sticky` key on
		// each entry round-trips through frappe.model.user_settings for free; it then
		// calls grid.reset_grid(), which re-runs setup_user_defined_columns() and so
		// re-derives grey_sticky_fieldnames and re-applies classes + offsets.
		wrap_before(proto, "update_user_settings_for_grid", function () {
			normalize_dialog_sticky(this);
		});

		wrap_before(proto, "reset_user_settings_for_grid", function () {
			if (this.grid) this.grid.grey_sticky_fieldnames = [];
		});
	}

	function mark_sticky_cell(grid_row, $col, df) {
		if (!$col || !$col.length || !df || !df.fieldname) return;
		if (!$col.attr("data-fieldname")) $col.attr("data-fieldname", df.fieldname);

		const names = (grid_row && grid_row.grid && grid_row.grid.grey_sticky_fieldnames) || [];
		const order = names.indexOf(df.fieldname);

		if (sticky_enabled() && order > -1) {
			$col.addClass(STICKY_CLASS).attr("data-sticky-order", order);
		} else {
			$col.removeClass(STICKY_CLASS).removeAttr("data-sticky-order");
		}
	}

	function stamp_dialog_sticky(grid_row) {
		const names = (grid_row && grid_row.grid && grid_row.grid.grey_sticky_fieldnames) || [];
		(grid_row.selected_columns_for_grid || []).forEach(function (entry) {
			if (!entry) return;
			entry.sticky = names.indexOf(entry.fieldname) > -1 ? 1 : 0;
		});
	}

	function inject_sticky_toggles(grid_row) {
		if (!sticky_enabled()) return;
		const wrapper = grid_row && grid_row.fields_html_wrapper;
		if (!wrapper) return;

		const me = grid_row;
		const pin_label = __("Pin");
		const pin_title = __("Keep this column pinned to the left edge while the grid scrolls");

		// prepare_wrapper_for_columns() renders a col-1 / col-6 / col-4 header row
		// (grid_row.js:441-446). The body rows below get re-split to make room for the
		// Pin toggle, so the header has to be re-split identically or the "Fieldname"
		// and "Columns" captions sit over the wrong columns.
		$(wrapper)
			.find(".form-group > .row")
			.filter(function () {
				return !$(this).closest(".fields_order").length;
			})
			.first()
			.each(function () {
				const $header = $(this);
				if ($header.find(".grey-sticky-head").length) return;

				const $caption = $header.children(".col-6").first();
				if (!$caption.length) return;
				$caption.removeClass("col-6").addClass("col-4");

				$("<div class='col-2 grey-sticky-head'></div>")
					.text(pin_label)
					.insertAfter($caption);
			});

		$(wrapper)
			.find(".fields_order")
			.each(function () {
				const $row = $(this);
				if ($row.find(".grey-sticky-toggle").length) return;

				const fieldname = $row.attr("data-fieldname");
				if (!fieldname) return;

				// keep the existing col-1 / col-6 / col-4 / col-1 bootstrap row at 12
				const $label = $row.find(".row > .col-6").first();
				if (!$label.length) return;
				$label.removeClass("col-6").addClass("col-4");

				const entry = (me.selected_columns_for_grid || []).find(function (r) {
					return r && r.fieldname === fieldname;
				});

				const $toggle = $(
					"<div class='col-2 grey-sticky-toggle' style='padding-top: 5px;'>" +
						"<label class='grey-sticky-label'>" +
						"<input type='checkbox' class='grey-sticky-check'>" +
						"<span></span>" +
						"</label>" +
						"</div>"
				);
				$toggle.attr("title", pin_title);
				$toggle.find("span").text(pin_label);

				const $check = $toggle.find(".grey-sticky-check");
				$check.attr("data-fieldname", fieldname).attr("aria-label", pin_title);
				$check.prop("checked", !!(entry && entry.sticky));

				$toggle.insertAfter($label);

				// the whole .fields_order row is the Sortable drag handle
				$toggle.on("mousedown pointerdown click", function (e) {
					e.stopPropagation();
				});

				$check.on("change", function () {
					const on = this.checked ? 1 : 0;
					(me.selected_columns_for_grid || []).forEach(function (r) {
						if (r && r.fieldname === fieldname) r.sticky = on;
					});
				});
			});
	}

	/** Upstream sort_columns() rebuilds selected_columns_for_grid from the DOM and drops `sticky`. */
	function patch_sort_columns(proto) {
		const orig = proto.sort_columns;
		if (typeof orig !== "function") return;

		proto.sort_columns = function () {
			const previous = {};
			(this.selected_columns_for_grid || []).forEach(function (r) {
				if (r && r.fieldname) previous[r.fieldname] = r.sticky ? 1 : 0;
			});

			const ret = orig.apply(this, arguments);

			try {
				const wrapper = this.fields_html_wrapper;
				(this.selected_columns_for_grid || []).forEach(function (r) {
					if (!r || !r.fieldname) return;
					let on = previous[r.fieldname] ? 1 : 0;
					if (wrapper) {
						const $check = $(wrapper).find(
							".grey-sticky-check[data-fieldname='" + r.fieldname + "']"
						);
						if ($check.length) on = $check.is(":checked") ? 1 : 0;
					}
					r.sticky = on;
				});
			} catch (err) {
				log_error(err);
			}
			return ret;
		};
	}

	/**
	 * Upstream hard-throws when the total column width exceeds 10, which would make the
	 * raised column budget unusable — so with the enhancer on, the same check runs against
	 * the configured limit instead, and the sticky rules are enforced on top.
	 */
	function patch_validate_columns_width(proto) {
		const orig = proto.validate_columns_width;
		if (typeof orig !== "function") return;

		proto.validate_columns_width = function () {
			if (!enabled()) return orig.apply(this, arguments);

			const rows = this.selected_columns_for_grid || [];
			const limit = column_limit();
			const doctype = this.grid && this.grid.doctype;

			let total_column_width = 0.0;
			rows.forEach(function (row) {
				if (row && cint(row.columns) > 0) total_column_width += cint(row.columns);
			});
			if (total_column_width && total_column_width > limit) {
				frappe.throw(__("The total column width cannot be more than {0}.", [limit]));
			}

			// Upstream caps the TOTAL at 10, which also caps any single column at 10.
			// We raise the total to `limit`, so a per-column cap has to be reinstated
			// explicitly: make_column stamps `col-xs-<columns>` and the stylesheet only
			// emits width rules up to MAX_COLUMN_WIDTH. A wider class would get no rule
			// at all and the heading, filter and data rows would drift out of alignment.
			const too_wide = rows.filter(function (row) {
				return row && cint(row.columns) > MAX_COLUMN_WIDTH;
			});
			if (too_wide.length) {
				frappe.throw(
					__("A single column cannot be wider than {0}.", [MAX_COLUMN_WIDTH])
				);
			}

			if (!sticky_enabled()) return;

			const sticky = [];
			let seen_unpinned = false;
			rows.forEach(function (row) {
				if (!row) return;
				if (row.sticky) {
					if (seen_unpinned) {
						frappe.throw(
							__(
								"Pinned columns must come first. Move {0} to the top of the list or unpin it.",
								[column_label(doctype, row.fieldname)]
							)
						);
					}
					sticky.push(row.fieldname);
				} else {
					seen_unpinned = true;
				}
			});

			if (sticky.length > max_sticky()) {
				frappe.throw(__("You can pin at most {0} columns.", [max_sticky()]));
			}
		};
	}

	function column_label(doctype, fieldname) {
		try {
			const docfield = doctype && frappe.meta.get_docfield(doctype, fieldname);
			if (docfield && docfield.label) return __(docfield.label, null, docfield.parent);
		} catch (err) {
			// fall through to the fieldname
		}
		return fieldname;
	}

	/** Guarantee the payload about to be saved carries a clean, contiguous leading run. */
	function normalize_dialog_sticky(grid_row) {
		const rows = grid_row.selected_columns_for_grid || [];
		const allow = sticky_enabled();
		const limit = max_sticky();
		const names = [];
		let seen_unpinned = false;

		rows.forEach(function (row) {
			if (!row) return;
			const on = allow && row.sticky && !seen_unpinned && names.length < limit ? 1 : 0;
			row.sticky = on;
			if (on) {
				names.push(row.fieldname);
			} else {
				seen_unpinned = true;
			}
		});

		if (grid_row.grid) grid_row.grid.grey_sticky_fieldnames = names;
	}

	/* ------------------------------------------------------- per-instance setup */

	function enhance_instance(grid) {
		if (!grid || !enabled()) return;
		if (!body_flags_done) apply_body_flags();

		let $container = null;
		if (grid.form_grid && grid.form_grid.length) {
			$container = grid.form_grid.closest(".form-grid-container");
		}
		if ((!$container || !$container.length) && grid.wrapper) {
			$container = grid.wrapper.find(".form-grid-container").first();
		}
		// grid.make() has not run yet (the Grid constructor builds no DOM) — the
		// patched make() will call us again once the wrapper exists
		if (!$container || !$container.length) return;

		const node = $container[0];
		if (node.dataset.greyGridScroll !== "1") {
			node.dataset.greyGridScroll = "1";
			$container.addClass("grey-grid-scroll");
			setup_dropdown_escape($container);
		}

		$container.toggleClass("grey-grid-wide", needs_wide_layout(grid));

		refresh_sticky(grid);
	}

	/**
	 * Does this grid actually need the fixed-width scrolling layout?
	 *
	 * Only when the columns no longer fit Frappe's 12-unit bootstrap row. Stock Frappe
	 * caps `setup_visible_columns()` at STOCK_COLUMN_CAP units precisely so a grid never
	 * overflows, and lays those columns out as percentages that fill the container and
	 * line the heading, filter and data rows up exactly.
	 *
	 * On a child table that already fits (Sales Invoice Item renders 7 columns totalling
	 * 10 units, so the raised budget appends nothing) swapping that for pixel widths is
	 * all risk and no benefit: any per-row difference in the non-flexible cells shows up
	 * as drift between the heading and the data rows. So leave those grids completely
	 * stock and only switch the layout on where the raised budget actually bought us
	 * extra columns — which is also the only case where there is anything to scroll and
	 * therefore anything to pin.
	 */
	function needs_wide_layout(grid) {
		if (!enabled() || !grid) return false;

		// The exact signal: append_overflow_columns() counts the columns it added
		// BEYOND the set stock Frappe had already accepted. Re-deriving the total
		// colsize here instead would mean re-implementing Frappe's own arithmetic
		// (its running total seeds at 1, and update_default_colsize() fills in a
		// per-fieldtype size for any field with no explicit `columns`) and getting a
		// different answer than the code that actually built the row.
		return cint(grid.grey_appended_columns) > 0;
	}

	/**
	 * A scroll container clips its overflow, so an Awesomplete dropdown opened in the
	 * last grid row (frappe renders its <ul> inside the cell) would be cut off. Lift an
	 * open dropdown to position:fixed for as long as it is open, then put it back.
	 */
	function setup_dropdown_escape($container) {
		let $dropdown = null;
		let anchor = null;

		function place() {
			if (!$dropdown || !$dropdown.length || !anchor || !anchor.isConnected) {
				restore();
				return;
			}
			// Only a wide grid sets overflow-x, so only a wide grid clips the dropdown.
			// On a stock-width grid leave Awesomplete's own positioning alone.
			if (!$container.hasClass("grey-grid-wide")) {
				restore();
				return;
			}
			const rect = anchor.getBoundingClientRect();

			// frappe's awesomeplete.scss sets `& > [role="listbox"] { width: 100% }`.
			// That percentage resolves against the offset parent while the dropdown is
			// position:absolute, but against the INITIAL CONTAINING BLOCK (the viewport)
			// the moment we switch it to position:fixed — so every Link dropdown would
			// become as wide as the browser window. Pin an explicit pixel width, and
			// derive it from the anchor cell only: reading $dropdown.outerWidth() here
			// would measure the already-blown-out width on the second call.
			const width = Math.max(rect.width, 250);

			let left = rect.left;
			if (left + width > window.innerWidth - 8) {
				left = Math.max(8, window.innerWidth - width - 8);
			}
			$dropdown.css({
				position: "fixed",
				top: rect.bottom + "px",
				left: left + "px",
				right: "auto",
				width: width + "px",
				"min-width": width + "px",
				"max-width": "none",
				"z-index": 1055,
			});
		}

		function restore() {
			if ($dropdown && $dropdown.length) {
				$dropdown.css({
					position: "",
					top: "",
					left: "",
					right: "",
					width: "",
					"min-width": "",
					"max-width": "",
					"z-index": "",
				});
			}
			$dropdown = null;
			anchor = null;
			$container.off("scroll.greyGridDropdown");
			$(window).off("scroll.greyGridDropdown resize.greyGridDropdown");
		}

		$container.on("awesomplete-open", "input", function (e) {
			try {
				// a dropdown that never fired its close event must not leak inline styles
				restore();
				anchor = e.target;
				const $wrapper = $(anchor).closest(".awesomplete");
				$dropdown = $wrapper.length ? $wrapper.children("ul").first() : null;
				if (!$dropdown || !$dropdown.length) {
					restore();
					return;
				}
				place();
				$container.on("scroll.greyGridDropdown", place);
				$(window).on("scroll.greyGridDropdown resize.greyGridDropdown", place);
			} catch (err) {
				log_error(err);
				restore();
			}
		});

		$container.on("awesomplete-close", "input", function () {
			try {
				restore();
			} catch (err) {
				log_error(err);
			}
		});
	}

	/* ---------------------------------------------------------------- bootstrap */

	function attach(grid) {
		if (!grid || !enabled()) return;
		apply_body_flags();
		patch_grid_prototype(Object.getPrototypeOf(grid));
		enhance_instance(grid);
	}

	function init() {
		if (window[MODULE_FLAG]) return;

		// frappe/www/app.html assigns frappe.boot inline (line 54) before it renders the
		// app_include_js <script> tags (lines 69-70), so boot is already available here.
		// When it is and the feature is off — including when the grey_theme_ui key is
		// absent entirely, i.e. the DocType has not been migrated in — leave without
		// replacing ControlTable. A disabled site stays byte-identical to stock Frappe.
		if (frappe.boot && !enabled()) {
			window[MODULE_FLAG] = true;
			return;
		}

		window[MODULE_FLAG] = true;

		const BaseControlTable = frappe.ui.form.ControlTable;
		if (!BaseControlTable) return;

		frappe.ui.form.ControlTable = class GreyThemeControlTable extends BaseControlTable {
			make() {
				super.make();
				// a throw here would break every form carrying a child table
				try {
					attach(this.grid);
				} catch (err) {
					log_error(err);
				}
			}
		};

		$(function () {
			try {
				apply_body_flags();
			} catch (err) {
				log_error(err);
			}
		});
	}

	init();
})();
