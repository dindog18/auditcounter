import json
from unittest.mock import patch

from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .services.help_assistant import NO_ANSWER, TOPICS


@override_settings(HELP_ASSISTANT_ENABLED=True)
class HelpAssistantTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.url = reverse("ask_help")
        self.query = {
            "page": "document", "workspace": "DOC_EXTRACTION",
            "question": "How can I correct extracted text?",
            "history": [{"question": "Where do I review a document?", "answer": "Open Documents."}],
        }

    def post(self, **changes):
        return self.client.post(self.url, self.query | changes, content_type="application/json")

    @override_settings(HELP_ASSISTANT_ENABLED=False)
    def test_disabled_feature_preserves_the_tour(self):
        page = self.client.get(reverse("DOC_EXTRACTION:document_list"))
        self.assertNotContains(page, "Ask AuditCounter")
        self.assertContains(page, "data-help-start")
        self.assertEqual(self.post().status_code, 404)

    def test_menu_and_endpoint_require_valid_post(self):
        client = Client(enforce_csrf_checks=True)
        page = client.get(reverse("DOC_EXTRACTION:document_list"))
        self.assertContains(page, "Ask AuditCounter")
        self.assertContains(page, 'data-page="documents"')
        self.assertEqual(client.get(self.url).status_code, 405)
        self.assertEqual(client.post(self.url, self.query, content_type="application/json").status_code, 403)
        for changes in (
            {"page": "/documents/123/?private=1"},
            {"workspace": "unexpected"},
            {"question": " "},
            {"question": "a" * 1001},
            {"history": self.query["history"] * 4},
            {"document_text": "private record"},
        ):
            with self.subTest(changes=changes):
                self.assertEqual(self.post(**changes).status_code, 400)

    @patch("document_extraction.services.help_assistant.get_env")
    @patch("document_extraction.services.help_assistant.invoke_with_llm")
    def test_uses_page_guidance_and_returns_only_application_links(self, invoke, env):
        env.side_effect = {"CONFIG_ASSISTANT_LLM_PROVIDER": "openai", "CONFIG_ASSISTANT_OPENAI_MODEL": "test"}.get
        invoke.return_value = {"choices": [{"message": {"content": json.dumps({
            "answer": "Open the extraction attempt and choose Edit Markdown.",
            "sources": list(TOPICS)[:3],
        })}}]}
        response = self.post()
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertEqual(response.json()["sources"][0]["url"], reverse("DOC_EXTRACTION:document_list"))
        provider, payload = invoke.await_args.args
        self.assertEqual(provider, "openai")
        content = json.loads(payload["messages"][1]["content"])
        self.assertEqual(content["page"], "Review a document")
        self.assertEqual(content["history"], self.query["history"])
        self.assertIn("Compare", " ".join(content["page_guidance"]))
        self.assertNotIn("tools", payload)
        for _, route, _ in TOPICS.values():
            self.assertTrue(reverse(route).startswith("/"))

        invoke.return_value["choices"][0]["message"]["content"] = '{"answer":"","sources":[]}'
        self.assertEqual(self.post().json(), {"answer": NO_ANSWER, "sources": []})
        invoke.return_value["choices"][0]["message"]["content"] = '{"answer":"Visit this","sources":["https://example.com"]}'
        with self.assertLogs("document_extraction.help_views", level="WARNING"):
            failed = self.post()
        self.assertEqual(failed.status_code, 503)
        self.assertNotIn("example.com", failed.content.decode())

    @patch("document_extraction.help_views.answer_question", return_value={"answer": NO_ANSWER, "sources": []})
    @patch("document_extraction.help_views.time", return_value=1000)
    def test_rate_limit_bounds_provider_calls(self, _, answer):
        for _ in range(10):
            self.assertEqual(self.post().status_code, 200)
        self.assertEqual(self.post().status_code, 429)
        self.assertEqual(answer.call_count, 10)
