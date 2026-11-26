# Copyright (c) 2026, Enfono Technologies and contributors
# For license information, please see license.txt
"""Fateh AI tests.

None of these call a real LLM: providers are exercised with a fake HTTP response, and the agent
loop with a scripted stream. Settings are patched in memory (config.get_settings) rather than
written to the AI Settings Single, so a run never repoints a live site; the one test that must
write the Single (the key-migration patch) restores it and clears the document cache.
"""

import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils.password import get_decrypted_password, set_encrypted_password

from grey_theme.fateh_ai import agent, api, config, providers, tools

TEST_ROLE = "Fateh AI Test Role"
TEST_USER = "fateh-ai-test@example.com"


def make_settings(**overrides):
	s = frappe._dict(
		enabled=1,
		assistant_name="Fateh AI",
		show_launcher=1,
		allowed_roles=[],
		daily_message_limit=0,
		provider="Groq",
		kind="openai",
		base_url="https://llm.invalid/v1",
		api_key="test-key",
		key_optional=False,
		models=["model-a", "model-b"],
		temperature=0.2,
		max_output_tokens=512,
		max_iterations=4,
		request_timeout=30,
		extra_instructions="",
		enable_sql_tool=0,
	)
	s.update(overrides)
	return s


class FakeResponse:
	def __init__(self, status=200, lines=None, body=None):
		self.status_code = status
		self.lines = lines or []
		self.body = body or {}
		self.reason = "fake"
		self.text = json.dumps(self.body)

	def iter_lines(self, decode_unicode=False):
		for line in self.lines:
			yield line.encode()

	def json(self):
		return self.body

	def close(self):
		pass


def sse(*chunks):
	lines = []
	for c in chunks:
		lines.append("data: " + (c if isinstance(c, str) else json.dumps(c)))
		lines.append("")
	return lines


# ------------------------------------------------------------------------------ providers


class TestProviders(FrappeTestCase):
	def test_openai_translation(self):
		messages = [
			{"role": "user", "content": [{"type": "text", "text": "hi"}]},
			{
				"role": "assistant",
				"content": [
					{"type": "text", "text": "checking"},
					{"type": "tool_use", "id": "c1", "name": "count_records", "input": {"doctype": "ToDo"}},
				],
			},
			{"role": "user", "content": [{"type": "tool_result", "tool_use_id": "c1", "content": "{\"count\": 2}"}]},
		]
		out = providers.to_openai_messages(messages, "sys")
		self.assertEqual([m["role"] for m in out], ["system", "user", "assistant", "tool"])
		self.assertEqual(out[2]["tool_calls"][0]["function"]["name"], "count_records")
		self.assertEqual(json.loads(out[2]["tool_calls"][0]["function"]["arguments"]), {"doctype": "ToDo"})
		self.assertEqual(out[3]["tool_call_id"], "c1")

	def test_openai_stream_assembles_tool_calls(self):
		lines = sse(
			{"choices": [{"delta": {"content": "Let me "}}]},
			{"choices": [{"delta": {"content": "check."}}]},
			{"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c1", "function": {"name": "count_records", "arguments": "{\"doc"}}]}}]},
			{"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": "type\": \"ToDo\"}"}}]}, "finish_reason": "tool_calls"}], "x_groq": {"usage": {"prompt_tokens": 11, "completion_tokens": 7}}},
			"[DONE]",
		)
		with patch.object(providers.requests, "post", return_value=FakeResponse(lines=lines)):
			events = list(providers.stream_chat(make_settings(), messages=[], system="s", tools=[]))
		self.assertEqual(events[0], {"type": "model", "model": "model-a"})
		text = "".join(e["text"] for e in events if e["type"] == "text")
		self.assertEqual(text, "Let me check.")
		tool = next(e for e in events if e["type"] == "tool_use")
		self.assertEqual(tool["name"], "count_records")
		self.assertEqual(tool["input"], {"doctype": "ToDo"})
		usage = next(e for e in events if e["type"] == "usage")
		self.assertEqual((usage["input_tokens"], usage["output_tokens"]), (11, 7))
		self.assertEqual(events[-1], {"type": "stop", "reason": "tool_use"})

	def test_retired_model_falls_back_to_next(self):
		gone = FakeResponse(status=400, body={"error": {"code": "model_decommissioned", "message": "model decommissioned"}})
		ok = FakeResponse(lines=sse({"choices": [{"delta": {"content": "OK"}, "finish_reason": "stop"}]}, "[DONE]"))
		with patch.object(providers.requests, "post", side_effect=[gone, ok]) as post:
			events = list(providers.stream_chat(make_settings(), messages=[], system="s"))
		self.assertEqual(post.call_count, 2)
		self.assertEqual(json.loads(post.call_args_list[1].kwargs["data"])["model"], "model-b")
		self.assertEqual(events[0], {"type": "model", "model": "model-b"})

	def test_stop_interrupts_a_rate_limit_wait(self):
		limited = FakeResponse(status=429, body={"error": {"message": "Rate limit reached. Please try again in 20s."}})
		with patch.object(providers.requests, "post", return_value=limited), patch.object(providers.time, "sleep") as sleep:
			with self.assertRaises(providers.StopRequested):
				list(providers.stream_chat(make_settings(models=["only"]), messages=[], system="s", should_stop=lambda: True))
		sleep.assert_not_called()

	def test_bad_key_is_not_retried(self):
		denied = FakeResponse(status=401, body={"error": {"message": "invalid api key"}})
		with patch.object(providers.requests, "post", return_value=denied) as post:
			with self.assertRaises(providers.ProviderError):
				list(providers.stream_chat(make_settings(), messages=[], system="s"))
		self.assertEqual(post.call_count, 1)

	def test_anthropic_stream(self):
		lines = []
		for event in (
			{"type": "message_start", "message": {"usage": {"input_tokens": 20}}},
			{"type": "content_block_start", "index": 0, "content_block": {"type": "text"}},
			{"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Hi"}},
			{"type": "content_block_stop", "index": 0},
			{"type": "content_block_start", "index": 1, "content_block": {"type": "tool_use", "id": "t1", "name": "search_link"}},
			{"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": "{\"doctype\": \"Item\","}},
			{"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": " \"text\": \"pipe\"}"}},
			{"type": "content_block_stop", "index": 1},
			{"type": "message_delta", "delta": {"stop_reason": "tool_use"}, "usage": {"output_tokens": 9}},
			{"type": "message_stop"},
		):
			lines += [f"event: {event['type']}", "data: " + json.dumps(event), ""]
		settings = make_settings(kind="anthropic", provider="Anthropic")
		with patch.object(providers.requests, "post", return_value=FakeResponse(lines=lines)) as post:
			events = list(providers.stream_chat(settings, messages=[], system="s", tools=[]))
		self.assertIn("x-api-key", post.call_args.kwargs["headers"])
		tool = next(e for e in events if e["type"] == "tool_use")
		self.assertEqual(tool["input"], {"doctype": "Item", "text": "pipe"})
		self.assertEqual(next(e for e in events if e["type"] == "usage")["output_tokens"], 9)


# ------------------------------------------------------------------------------ tools


def ensure_test_user():
	if not frappe.db.exists("Role", TEST_ROLE):
		frappe.get_doc({"doctype": "Role", "role_name": TEST_ROLE, "desk_access": 1}).insert(ignore_permissions=True)
	if not frappe.db.exists("User", TEST_USER):
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": TEST_USER,
				"first_name": "Fateh Test",
				"send_welcome_email": 0,
				"user_type": "System User",
				"roles": [{"role": TEST_ROLE}],
			}
		)
		user.flags.no_welcome_mail = True
		user.insert(ignore_permissions=True)
	return TEST_USER


class TestTools(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.settings = make_settings()

	def tearDown(self):
		frappe.set_user("Administrator")

	def run_tool(self, name, args, settings=None):
		return tools.execute(name, args, settings or self.settings)

	def test_blocked_doctype_is_denied(self):
		res = self.run_tool("search_records", {"doctype": "User"})
		self.assertEqual(res.status, "Denied")
		res = self.run_tool("get_record", {"doctype": "AI Settings", "name": "AI Settings"})
		self.assertEqual(res.status, "Denied")

	def test_secret_looking_field_is_denied(self):
		res = self.run_tool("search_records", {"doctype": "ToDo", "fields": ["name", "api_key"]})
		self.assertEqual(res.status, "Denied")

	def test_unknown_operator_and_field_are_errors(self):
		res = self.run_tool("search_records", {"doctype": "ToDo", "filters": [["status", "drop table", "x"]]})
		self.assertEqual(res.status, "Error")
		res = self.run_tool("search_records", {"doctype": "ToDo", "filters": {"no_such_field": 1}})
		self.assertEqual(res.status, "Error")

	def test_missing_required_argument(self):
		res = self.run_tool("get_record", {"doctype": "ToDo"})
		self.assertEqual(res.status, "Error")
		self.assertIn("name", res.error)

	def test_search_count_and_aggregate(self):
		todo = frappe.get_doc({"doctype": "ToDo", "description": "fateh-ai-search-probe", "status": "Open"}).insert()
		res = self.run_tool("search_records", {"doctype": "ToDo", "filters": {"description": ["like", "%fateh-ai-search-probe%"]}, "fields": ["name", "status"]})
		self.assertEqual(res.status, "Success", res.error)
		data = json.loads(res.content)
		self.assertIn(todo.name, [r["name"] for r in data["rows"]])
		self.assertTrue(res.preview["columns"])

		res = self.run_tool("count_records", {"doctype": "ToDo", "filters": [["description", "like", "%fateh-ai-search-probe%"]]})
		self.assertEqual(json.loads(res.content)["count"], 1)

		res = self.run_tool("aggregate", {"doctype": "ToDo", "metrics": [{"function": "count"}], "group_by": ["status"]})
		self.assertEqual(res.status, "Success", res.error)
		self.assertTrue(any(r.get("status") == "Open" for r in json.loads(res.content)["rows"]))

		res = self.run_tool("aggregate", {"doctype": "ToDo", "metrics": [{"function": "sum", "field": "description"}]})
		self.assertEqual(res.status, "Error")  # sum of a text field is refused

		# min/max and periods must survive frappe's DatabaseQuery.extract_tables()
		res = self.run_tool(
			"aggregate",
			{
				"doctype": "ToDo",
				"metrics": [{"function": "count"}, {"function": "max", "field": "modified"}],
				"period": {"field": "creation", "by": "month"},
			},
		)
		self.assertEqual(res.status, "Success", res.error)
		row = json.loads(res.content)["rows"][0]
		self.assertIn("period_year", row)
		self.assertIn("max_modified", row)

	def test_party_outstanding_runs(self):
		if not frappe.db.exists("DocType", "Sales Invoice"):
			self.skipTest("ERPNext not installed")
		res = self.run_tool("party_outstanding", {"party_type": "Customer", "overdue_only": True, "limit": 3})
		self.assertEqual(res.status, "Success", res.error)
		res = self.run_tool(
			"aggregate",
			{
				"doctype": "Sales Invoice",
				"metrics": [{"function": "sum", "field": "Sales Invoice Item.base_net_amount"}],
				"filters": {"docstatus": 1},
				"period": {"field": "posting_date", "by": "quarter"},
				"limit": 4,
			},
		)
		self.assertEqual(res.status, "Success", res.error)

	def test_get_record_reads_permitted_document(self):
		todo = frappe.get_doc({"doctype": "ToDo", "description": "fateh-ai-get-probe"}).insert()
		res = self.run_tool("get_record", {"doctype": "ToDo", "name": todo.name})
		self.assertEqual(res.status, "Success", res.error)
		self.assertEqual(res.reference, ("ToDo", todo.name))
		self.assertEqual(json.loads(res.content)["record"]["description"].strip(), "fateh-ai-get-probe")

	def test_get_record_includes_child_rows(self):
		contact = frappe.get_doc(
			{
				"doctype": "Contact",
				"first_name": "Fateh Child Probe",
				"email_ids": [{"email_id": "fateh.child.probe@example.com", "is_primary": 1}],
			}
		).insert()
		res = self.run_tool("get_record", {"doctype": "Contact", "name": contact.name})
		self.assertEqual(res.status, "Success", res.error)
		record = json.loads(res.content)["record"]
		self.assertEqual(record["email_ids"][0]["email_id"], "fateh.child.probe@example.com")

	def test_rows_follow_the_users_permissions(self):
		todo = frappe.get_doc(
			{"doctype": "ToDo", "description": "fateh-ai-admin-only", "allocated_to": "Administrator"}
		).insert()
		user = ensure_test_user()
		frappe.set_user(user)
		res = self.run_tool("search_records", {"doctype": "ToDo", "filters": {"description": ["like", "%fateh-ai-admin-only%"]}})
		if res.status == "Success":
			self.assertNotIn(todo.name, [r["name"] for r in json.loads(res.content)["rows"]])
		else:
			self.assertEqual(res.status, "Denied")
		res = self.run_tool("get_record", {"doctype": "ToDo", "name": todo.name})
		self.assertEqual(res.status, "Denied")

	def test_no_permission_on_doctype_is_denied(self):
		if not frappe.db.exists("DocType", "Sales Invoice"):
			self.skipTest("ERPNext not installed")
		frappe.set_user(ensure_test_user())
		res = self.run_tool("aggregate", {"doctype": "Sales Invoice", "metrics": [{"function": "sum", "field": "base_grand_total"}]})
		self.assertEqual(res.status, "Denied")

	def test_sql_tool_is_gated(self):
		names = [t["name"] for t in tools.get_tools(make_settings(enable_sql_tool=0))]
		self.assertNotIn("run_sql_select", names)
		sql_settings = make_settings(enable_sql_tool=1)
		self.assertIn("run_sql_select", [t["name"] for t in tools.get_tools(sql_settings)])

		self.assertEqual(self.run_tool("run_sql_select", {"query": "select name from `tabToDo` limit 1"}, sql_settings).status, "Success")
		for bad in (
			"update `tabToDo` set status='Closed'",
			"select name, password from `__Auth`",
			"select name from `tabUser`",
			"select 1; select 2",
			"select * from `tabToDo` into outfile '/tmp/x'",
			"select sleep(5)",
		):
			res = self.run_tool("run_sql_select", {"query": bad}, sql_settings)
			self.assertIn(res.status, ("Denied", "Error"), bad)

		frappe.set_user(ensure_test_user())
		self.assertNotIn("run_sql_select", [t["name"] for t in tools.get_tools(sql_settings)])
		self.assertEqual(self.run_tool("run_sql_select", {"query": "select 1"}, sql_settings).status, "Denied")

	def test_report_links_prefill_filters(self):
		from grey_theme.fateh_ai import report_guide

		ar = frappe._dict(name="Accounts Receivable", report_type="Script Report", ref_doctype="Sales Invoice")
		link = report_guide.link(ar, {"company": "Steel Force WLL", "customer": ["A", "B"], "empty": None, "flag": True})
		self.assertEqual(
			link,
			"/app/query-report/Accounts%20Receivable?company=Steel%20Force%20WLL&customer=%5B%22A%22%2C%20%22B%22%5D&flag=1",
		)
		builder = frappe._dict(name="My Open Orders", report_type="Report Builder", ref_doctype="Sales Order")
		self.assertEqual(report_guide.link(builder), "/app/sales-order/view/report/My%20Open%20Orders")
		self.assertIn("ageing", report_guide.describe(ar))

	def test_list_reports_understands_plain_words(self):
		if not frappe.db.exists("Report", "Accounts Receivable"):
			self.skipTest("ERPNext not installed")
		res = self.run_tool("list_reports", {"keyword": "overdue customers"})
		self.assertEqual(res.status, "Success", res.error)
		first = json.loads(res.content)["reports"][0]
		self.assertEqual(first["report"], "Accounts Receivable")
		self.assertTrue(first["link"].startswith("/app/query-report/Accounts%20Receivable"))
		self.assertTrue(first["shows"])

	def test_js_report_filter_extraction(self):
		script = """frappe.query_reports["X"] = { filters: [
			{ fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company", reqd: 1,
			  default: frappe.defaults.get_user_default("Company") },
			{ fieldname: "from_date", label: __("From Date"), fieldtype: "Date", default: frappe.datetime.add_months(frappe.datetime.get_today(), -1) },
		]};"""
		filters = tools._extract_js_filters(script)
		self.assertEqual([f["fieldname"] for f in filters], ["company", "from_date"])
		self.assertEqual(filters[0]["required"], 1)
		self.assertEqual(filters[0]["options"], "Company")


# ------------------------------------------------------------------------------ agent + api


def new_conversation(user="Administrator", title="test"):
	doc = frappe.get_doc({"doctype": "Fateh AI Conversation", "user": user, "title": title})
	doc.insert(ignore_permissions=True)
	return doc.name


def add_message(conversation, role, content="", blocks=None, run_id="r0"):
	frappe.get_doc(
		{
			"doctype": "Fateh AI Message",
			"conversation": conversation,
			"role": role,
			"content": content,
			"blocks": json.dumps(blocks) if blocks is not None else None,
			"run_id": run_id,
		}
	).insert(ignore_permissions=True)


class TestHistory(FrappeTestCase):
	def test_dangling_tool_use_and_repeated_roles_are_repaired(self):
		conv = new_conversation()
		add_message(conv, "user", "first question", run_id="r1")
		add_message(
			conv, "assistant", "", [{"type": "tool_use", "id": "t1", "name": "count_records", "input": {}}], run_id="r1"
		)  # stopped before the tool ran: no tool row
		add_message(conv, "user", "second question", run_id="r2")
		history = agent.load_history(conv, current_run="r2")

		self.assertEqual([m["role"] for m in history], ["user", "assistant", "user"])
		results = [b for b in history[2]["content"] if b["type"] == "tool_result"]
		self.assertEqual([b["tool_use_id"] for b in results], ["t1"])
		self.assertEqual(history[2]["content"][0]["type"], "tool_result")  # results first
		self.assertEqual(history[2]["content"][-1]["text"], "second question")


def capture(events):
	"""Collect only Fateh AI events; document inserts publish their own (list_update...)."""

	def _capture(event, message=None, **kwargs):
		if event == agent.EVENT:
			events.append(message)

	return _capture


class TestAgentRun(FrappeTestCase):
	# frappe.db.rollback is patched in these tests: the agent rolls back before saving an
	# error, which in production only drops the failed step (the conversation was committed
	# by the request), but here would also drop this test's uncommitted conversation.

	def setUp(self):
		frappe.set_user("Administrator")

	def test_tool_loop_saves_messages_audit_and_events(self):
		conv = new_conversation()
		add_message(conv, "user", "how many todos?", run_id="run1")
		calls = {"n": 0}

		def scripted(settings, **kwargs):
			calls["n"] += 1
			yield {"type": "model", "model": "model-a"}
			if calls["n"] == 1:
				yield {"type": "text", "text": "Checking. "}
				yield {"type": "tool_use", "id": "t1", "name": "count_records", "input": {"doctype": "ToDo"}}
				yield {"type": "usage", "input_tokens": 100, "output_tokens": 10}
			else:
				yield {"type": "text", "text": "You have some ToDos."}
				yield {"type": "usage", "input_tokens": 150, "output_tokens": 12}

		events = []
		with patch.object(config, "get_settings", return_value=make_settings()), patch.object(
			agent.providers, "stream_chat", side_effect=scripted
		), patch.object(frappe, "publish_realtime", side_effect=capture(events)), patch.object(frappe.db, "rollback"):
			agent.run(conv, "run1", context={})

		rows = frappe.get_all(
			"Fateh AI Message", filters={"conversation": conv}, fields=["role", "content", "steps"], order_by="creation asc"
		)
		self.assertEqual([r.role for r in rows], ["user", "assistant", "tool", "assistant"])
		self.assertEqual(rows[-1].content, "You have some ToDos.")
		steps = json.loads(rows[1].steps)
		self.assertEqual((steps[0]["name"], steps[0]["status"]), ("count_records", "Success"))

		types = [e["type"] for e in events]
		for expected in ("start", "delta", "tool_start", "tool_end", "done"):
			self.assertIn(expected, types)

		audit = frappe.get_all("Fateh AI Audit Log", filters={"conversation": conv}, fields=["tool", "status"])
		self.assertEqual([(a.tool, a.status) for a in audit], [("count_records", "Success")])

		conv_doc = frappe.db.get_value(
			"Fateh AI Conversation", conv, ["message_count", "total_input_tokens", "total_output_tokens"], as_dict=True
		)
		self.assertEqual(conv_doc.message_count, 3)
		self.assertEqual((conv_doc.total_input_tokens, conv_doc.total_output_tokens), (250, 22))
		self.assertFalse(frappe.cache.get_value(agent.run_key(conv)))

	def test_stop_flag_is_seen_inside_the_job(self):
		conv = new_conversation()
		add_message(conv, "user", "count my todos", run_id="run3")
		# an earlier read in the same process memoises None in frappe.local.cache ...
		frappe.cache.get_value(agent.stop_key("run3"))
		# ... and the web request then sets the flag in Redis
		frappe.cache.set_value(agent.stop_key("run3"), 1, expires_in_sec=60)

		def scripted(settings, **kwargs):
			yield {"type": "model", "model": "model-a"}
			yield {"type": "tool_use", "id": "t1", "name": "count_records", "input": {"doctype": "ToDo"}}

		events = []
		with patch.object(config, "get_settings", return_value=make_settings()), patch.object(
			agent.providers, "stream_chat", side_effect=scripted
		), patch.object(frappe, "publish_realtime", side_effect=capture(events)), patch.object(frappe.db, "rollback"):
			agent.run(conv, "run3")
		self.assertEqual(events[-1]["type"], "stopped")
		self.assertFalse(frappe.get_all("Fateh AI Audit Log", filters={"conversation": conv}))

	def test_provider_error_is_saved_and_emitted(self):
		conv = new_conversation()
		add_message(conv, "user", "hello", run_id="run2")

		def failing(settings, **kwargs):
			raise providers.ProviderError("401: The API key was rejected")
			yield  # pragma: no cover

		events = []
		with patch.object(config, "get_settings", return_value=make_settings()), patch.object(
			agent.providers, "stream_chat", side_effect=failing
		), patch.object(frappe, "publish_realtime", side_effect=capture(events)), patch.object(frappe.db, "rollback"):
			agent.run(conv, "run2")
		last = frappe.get_all("Fateh AI Message", filters={"conversation": conv, "role": "assistant"}, fields=["is_error", "content"])
		self.assertEqual(last[0].is_error, 1)
		self.assertEqual(events[-1]["type"], "error")


class TestApi(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_other_users_cannot_read_a_conversation(self):
		conv = new_conversation("Administrator")
		frappe.set_user(ensure_test_user())
		with patch.object(config, "get_settings", return_value=make_settings()):
			with self.assertRaises(frappe.PermissionError):
				api.get_conversation(conv)
			self.assertNotIn(conv, [c.name for c in api.list_conversations()])

	def test_disabled_or_role_gated(self):
		user = ensure_test_user()
		self.assertFalse(config.get_access(user, make_settings(enabled=0))[0])
		self.assertFalse(config.get_access(user, make_settings(allowed_roles=["System Manager"]))[0])
		self.assertTrue(config.get_access(user, make_settings(allowed_roles=[TEST_ROLE]))[0])
		self.assertFalse(config.get_access("Guest", make_settings())[0])

	def test_send_message_queues_a_run_and_respects_daily_limit(self):
		queued = []
		with patch.object(config, "get_settings", return_value=make_settings(daily_message_limit=1000)), patch.object(
			frappe, "enqueue", side_effect=lambda *a, **kw: queued.append(kw)
		):
			res = api.send_message("Top customers?")
		self.assertEqual(queued[0]["conversation"], res["conversation"])
		self.assertEqual(frappe.db.get_value("Fateh AI Conversation", res["conversation"], "user"), "Administrator")
		frappe.cache.delete_value(agent.run_key(res["conversation"]))

		used = api._messages_today("Administrator")
		with patch.object(config, "get_settings", return_value=make_settings(daily_message_limit=used)), patch.object(
			frappe, "enqueue"
		):
			with self.assertRaises(frappe.ValidationError):
				api.send_message("one more")


# ------------------------------------------------------------------------------ patch


class TestLegacyKeyPatch(FrappeTestCase):
	DT = "AI Settings"

	def setUp(self):
		self.before = frappe.db.get_singles_dict(self.DT)
		self.before_key = get_decrypted_password(self.DT, self.DT, "api_key", raise_exception=False)

	def tearDown(self):
		restore = {k: self.before.get(k) for k in ("groq_api_key", "deepseek_api_key", "provider", "api_key", "enabled", "show_launcher", "default_provider")}
		frappe.db.set_single_value(self.DT, restore)
		if self.before_key:
			set_encrypted_password(self.DT, self.DT, self.before_key, "api_key")
		else:
			frappe.db.delete("__Auth", {"doctype": self.DT, "name": self.DT, "fieldname": "api_key"})
		frappe.clear_document_cache(self.DT, self.DT)

	def test_plaintext_key_moves_into_password_field(self):
		from grey_theme.patches.v2_0 import migrate_ai_settings_keys

		frappe.db.delete("__Auth", {"doctype": self.DT, "name": self.DT, "fieldname": "api_key"})
		frappe.db.set_single_value(self.DT, {"groq_api_key": "gsk_test_123", "api_key": None, "enabled": 0, "default_provider": "Groq"})
		migrate_ai_settings_keys.execute()

		values = frappe.db.get_singles_dict(self.DT)
		self.assertEqual(get_decrypted_password(self.DT, self.DT, "api_key"), "gsk_test_123")
		self.assertFalse(values.get("groq_api_key"))
		self.assertEqual(values.get("provider"), "Groq")
		self.assertEqual(int(values.get("enabled")), 1)
		self.assertEqual(int(values.get("show_launcher")), 0)

		migrate_ai_settings_keys.execute()  # idempotent: nothing left to migrate
		self.assertEqual(get_decrypted_password(self.DT, self.DT, "api_key"), "gsk_test_123")
