// Copyright (c) 2026, Enfono Technologies and contributors
// For license information, please see license.txt

frappe.ui.form.on("Grey Theme UI Settings", {
	refresh(frm) {
		frm.set_intro(
			__(
				"These settings are delivered to the desk at login. After saving, reload the page (Ctrl/Cmd + Shift + R) for the change to take effect."
			),
			"blue"
		);
	},
});
