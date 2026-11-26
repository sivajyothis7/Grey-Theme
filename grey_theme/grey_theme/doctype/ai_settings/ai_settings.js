// Copyright (c) 2025, siva and contributors
// For license information, please see license.txt

frappe.ui.form.on("AI Settings", {
	refresh(frm) {
		frm.add_custom_button(__("Test Connection"), () => {
			if (frm.is_dirty()) {
				frappe.msgprint(__("Save the settings first."));
				return;
			}
			frappe.call({
				method: "grey_theme.fateh_ai.api.test_connection",
				freeze: true,
				freeze_message: __("Asking the model to reply…"),
				callback: (r) => {
					const res = r.message || {};
					if (res.ok) {
						frappe.msgprint({
							title: __("Connected"),
							indicator: "green",
							message: __("Model {0} replied in {1} ms: {2}", [
								frappe.utils.escape_html(res.model || ""),
								res.latency_ms,
								frappe.utils.escape_html(res.reply || ""),
							]),
						});
					} else {
						frappe.msgprint({
							title: __("Connection failed"),
							indicator: "red",
							message: frappe.utils.escape_html(res.message || __("Unknown error")),
						});
					}
				},
			});
		});

		frm.add_custom_button(__("Fetch Models"), () => {
			if (frm.is_dirty()) {
				frappe.msgprint(__("Save the settings first."));
				return;
			}
			frappe.call({
				method: "grey_theme.fateh_ai.api.list_models",
				freeze: true,
				callback: (r) => {
					const models = (r.message && r.message.models) || [];
					if (!models.length) {
						frappe.msgprint(__("The provider returned no models."));
						return;
					}
					const d = new frappe.ui.Dialog({
						title: __("Available Models"),
						fields: [
							{
								fieldname: "model",
								fieldtype: "Select",
								label: __("Model"),
								options: models,
								default: frm.doc.model || models[0],
							},
						],
						primary_action_label: __("Use this model"),
						primary_action(values) {
							frm.set_value("model", values.model);
							d.hide();
						},
					});
					d.show();
				},
			});
		});

		if (frm.doc.enabled) {
			frm.add_custom_button(__("Open Assistant"), () => frappe.set_route("ai-chat"));
		}
	},
});
