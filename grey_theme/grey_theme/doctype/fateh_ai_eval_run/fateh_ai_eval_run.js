// Copyright (c) 2026, Enfono Technologies and contributors
// For license information, please see license.txt

frappe.ui.form.on("Fateh AI Eval Run", {
	refresh(frm) {
		clearTimeout(frm._fai_poll);
		if (["Queued", "Running"].includes(frm.doc.status)) {
			frm.dashboard.set_headline(
				__("Asking the test questions… {0} of them answered so far. This page refreshes by itself.", [
					(frm.doc.results || []).length,
				])
			);
			frm._fai_poll = setTimeout(() => {
				if (frappe.get_route_str() === `Form/Fateh AI Eval Run/${frm.doc.name}`) frm.reload_doc();
			}, 10000);
		} else if (frm.doc.status === "Completed") {
			const color = frm.doc.failed ? "orange" : "green";
			frm.dashboard.set_headline(
				__("{0} of {1} answers passed ({2}%).", [frm.doc.passed, frm.doc.total, frm.doc.score]),
				color
			);
		}
		if (!["Queued", "Running"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Run Again"), () => {
				frappe.call({
					method: "grey_theme.fateh_ai.api.start_eval_run",
					freeze: true,
					callback: (r) => r.message && frappe.set_route("Form", "Fateh AI Eval Run", r.message.name),
				});
			});
		}
	},
});
