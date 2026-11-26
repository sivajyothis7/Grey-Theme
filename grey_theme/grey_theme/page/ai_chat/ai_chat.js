// Copyright (c) 2026, Enfono Technologies and contributors
// For license information, please see license.txt
//
// Full-page Fateh AI. The chat component itself lives in the desk bundle
// (grey_theme/public/js/fateh_ai/chat_app.js, loaded via app_include_js).

frappe.pages["ai-chat"].on_page_load = function (wrapper) {
	const name = (frappe.boot.fateh_ai && frappe.boot.fateh_ai.name) || "Fateh AI";
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: name,
		single_column: true,
	});
	$(wrapper).addClass("fai-page");

	const ChatApp = window.grey_theme && grey_theme.fateh_ai && grey_theme.fateh_ai.ChatApp;
	if (!ChatApp) {
		// Usually a desk tab opened before the assistant was installed/updated: its script list
		// is from the old build. A reload fetches the new one.
		const box = $("<div class='text-center' style='padding: 48px 16px'>");
		box.append($("<p class='text-muted'>").text(__("The assistant was updated. Reload the page to load it.")));
		box.append(
			$("<button class='btn btn-primary btn-sm'>")
				.text(__("Reload"))
				.on("click", () => window.location.reload())
		);
		box.append(
			$("<p class='text-muted small' style='margin-top: 16px'>").text(
				__("If this keeps showing, ask your administrator to run: bench build --app grey_theme")
			)
		);
		$(page.body).append(box);
		return;
	}

	const app = new ChatApp({ parent: page.body, mode: "page" });
	grey_theme.fateh_ai.page_app = app;

	if (grey_theme.fateh_ai.pending_open) {
		const conversation = grey_theme.fateh_ai.pending_open;
		grey_theme.fateh_ai.pending_open = null;
		// wait for bootstrap before opening
		setTimeout(() => app.open(conversation), 400);
	}
};

frappe.pages["ai-chat"].on_page_show = function () {
	const app = window.grey_theme && grey_theme.fateh_ai && grey_theme.fateh_ai.page_app;
	if (app && grey_theme.fateh_ai.pending_open) {
		const conversation = grey_theme.fateh_ai.pending_open;
		grey_theme.fateh_ai.pending_open = null;
		app.open(conversation);
	}
};
