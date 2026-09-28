// Copyright (c) 2026, Enfono Technologies and contributors
// For license information, please see license.txt

/**
 * Grey Theme desk UI bundle.
 *
 * Frappe's build picks this file up because of the ".bundle.js" suffix and emits
 * /assets/grey_theme/dist/js/grey_theme_ui.bundle.<hash>.js, which hooks.py loads
 * through app_include_js as "grey_theme_ui.bundle.js".
 *
 * Boot ordering (frappe v15): frappe/www/app.html assigns `frappe.boot` inline at
 * line 54 and only renders the app_include_js <script> tags at lines 69-70, so
 * frappe.boot — and with it frappe.boot.grey_theme_ui, published by grey_theme's
 * extend_bootinfo hook — is already populated when the two modules below evaluate.
 * No deferred-init queue is needed: each module reads its own flag directly and
 * no-ops silently when it is 0 or the key is absent, which also makes importing
 * them unconditionally safe on a site that has not migrated the DocType in yet.
 */

import "./ui/grid_enhancer";
import "./ui/split_view_menu";

/**
 * Convenience accessors for OTHER code (client scripts, custom app JS).
 *
 * Deliberately not used by the two modules above: ES imports are hoisted, so both
 * of them finish executing before these assignments run. Anything that wants these
 * helpers must call them from a later callback — form events, app_ready, a click
 * handler — never at its own module top level.
 */
frappe.provide("grey_theme.ui");

grey_theme.ui.get_settings = function () {
	return (frappe.boot && frappe.boot.grey_theme_ui) || {};
};

grey_theme.ui.is_enabled = function (flag) {
	return !!grey_theme.ui.get_settings()[flag];
};
