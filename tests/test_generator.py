import io
import json
import os
import ssl
import sys
import unittest
import urllib.error
from types import SimpleNamespace
from unittest.mock import Mock, patch

from careloop import engine, generator


def completed(source=engine.DEFAULT_SOURCE):
    return {
        "id": "resp_test", "status": "completed",
        "output": [{"type": "message", "role": "assistant", "status": "completed",
                    "content": [{"type": "output_text", "text": source}]}],
    }


class GeneratorTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {"OPENAI_API_KEY": "unit-test-secret"}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def draft(self, response=None, prompt=generator.DEFAULT_PROMPT):
        response = completed() if response is None else response
        with patch.object(generator, "urlopen", return_value=io.BytesIO(json.dumps(response).encode())) as request:
            result = generator.generate(prompt)
        return result, request

    def test_request_is_bounded_and_does_not_store_response(self):
        result, mocked = self.draft()
        request = mocked.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(request.full_url, "https://api.openai.com/v1/responses")
        self.assertEqual(request.method, "POST")
        self.assertEqual(request.get_header("Authorization"), "Bearer unit-test-secret")
        self.assertEqual(mocked.call_args.kwargs, {"timeout": 45})
        self.assertEqual(payload["model"], "gpt-6-astra")
        self.assertEqual(payload["max_output_tokens"], 4096)
        self.assertEqual(payload["reasoning"], {"effort": "low"})
        self.assertIs(payload["store"], False)
        self.assertIn(engine.SPEC_SOURCE, payload["instructions"])
        self.assertIn("DAVID-66", payload["instructions"])
        self.assertIn("C17", payload["instructions"])
        self.assertIn("exactly one function: def care(s):", payload["instructions"])
        for field in engine.FIELDS:
            self.assertIn("s." + field, payload["instructions"])
        self.assertEqual(payload["input"], generator.DEFAULT_PROMPT)
        self.assertEqual(result, {"source": engine.DEFAULT_SOURCE.strip(), "model": "gpt-6-astra",
                                 "response_id": "resp_test", "prompt": generator.DEFAULT_PROMPT,
                                 "generation_mode": "live"})

    def test_settings_do_not_expose_key_and_environment_overrides_work(self):
        with patch.dict(os.environ, {"VERIFIEDCARE_MODEL": "configured-model", "OPENAI_BASE_URL": "https://provider.example/v1/"}):
            self.assertEqual(generator.settings(), {"available": True, "model": "configured-model"})
            result, mocked = self.draft()
        self.assertEqual(result["model"], "configured-model")
        self.assertEqual(mocked.call_args.args[0].full_url, "https://provider.example/v1/responses")
        self.assertNotIn("unit-test-secret", json.dumps(result))

    def test_missing_key_is_reported_without_request(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": " "}), patch.object(generator, "urlopen") as mocked:
            self.assertFalse(generator.settings()["available"])
            with self.assertRaisesRegex(generator.GenerationError, "not configured"):
                generator.generate(generator.DEFAULT_PROMPT)
            mocked.assert_not_called()

    def test_prompt_limits_are_checked_before_request(self):
        for prompt in (None, "", " ", "x" * 2001, 10):
            with self.subTest(prompt_type=type(prompt).__name__), patch.object(generator, "urlopen") as mocked:
                with self.assertRaises(generator.GenerationError):
                    generator.generate(prompt)
                mocked.assert_not_called()

    def test_reads_all_output_text_parts_and_ignores_reasoning(self):
        response = completed()
        response["output"] = [
            {"type": "reasoning", "summary": [{"type": "summary_text", "text": "do not return this"}]},
            {"type": "message", "role": "assistant", "content": [
                {"type": "output_text", "text": "def care(s):\n"},
                {"type": "output_text", "text": '    return "await_culture"\n'},
            ]},
        ]
        result, _ = self.draft(response)
        self.assertEqual(result["source"], 'def care(s):\n    return "await_culture"')

    def test_optional_fence_is_stripped(self):
        for language in ("python", "py", ""):
            with self.subTest(language=language):
                result, _ = self.draft(completed("```" + language + "\n" + engine.DEFAULT_SOURCE + "```"))
                self.assertEqual(result["source"], engine.DEFAULT_SOURCE.strip())

    def test_incomplete_and_missing_responses_are_rejected(self):
        for response in ({}, [], {"status": "incomplete", "output": []},
                         {"status": "completed", "output": []},
                         {**completed(), "incomplete_details": {"reason": "max_output_tokens"}},
                         {**completed(), "error": {"message": "private payload"}}):
            with self.subTest(response_type=type(response).__name__):
                with self.assertRaises(generator.GenerationError):
                    self.draft(response)

    def test_refusal_is_rejected_even_if_code_also_present(self):
        response = completed()
        response["output"][0]["content"].append({"type": "refusal", "refusal": "private refusal text"})
        with self.assertRaisesRegex(generator.GenerationError, "declined") as caught:
            self.draft(response)
        self.assertNotIn("private refusal", str(caught.exception))

    def test_invalid_or_oversized_code_is_never_executed(self):
        for source in ("", "x" * 12001, "import os\nos.remove('something')", "Here is your code:\n" + engine.DEFAULT_SOURCE):
            with self.subTest(source_length=len(source)):
                with self.assertRaises(generator.GenerationError):
                    self.draft(completed(source))

    def test_valid_grammar_is_returned_even_when_spec_would_reject_it(self):
        source = 'def care(s):\n    return "resolved"\n'
        result, _ = self.draft(completed(source))
        self.assertEqual(result["source"], source.strip())
        self.assertFalse(engine.verify_source(result["source"])["valid"])

    def test_http_error_is_sanitized_and_not_retried(self):
        for code in (401, 403, 429, 500):
            error = urllib.error.HTTPError("https://example.invalid", code, "unit-test-secret private failure", {}, io.BytesIO(b"private response"))
            with self.subTest(code=code), patch.object(generator, "urlopen", side_effect=error) as mocked:
                with self.assertRaises(generator.GenerationError) as caught:
                    generator.generate(generator.DEFAULT_PROMPT)
                mocked.assert_called_once()
                self.assertNotIn("unit-test-secret", str(caught.exception))
                self.assertNotIn("private", str(caught.exception))

    def test_network_and_header_errors_are_sanitized(self):
        for error in (TimeoutError("private"), urllib.error.URLError("private"), OSError("private"), ValueError("unit-test-secret")):
            with self.subTest(error_type=type(error).__name__), patch.object(generator, "urlopen", side_effect=error):
                with self.assertRaises(generator.GenerationError) as caught:
                    generator.generate(generator.DEFAULT_PROMPT)
                self.assertNotIn("private", str(caught.exception))
                self.assertNotIn("unit-test-secret", str(caught.exception))

    def test_unreadable_and_oversized_provider_responses_are_rejected(self):
        for raw in (b"not JSON", b"\xff", b"x" * (generator.MAX_RESPONSE_BYTES + 1)):
            with self.subTest(response_size=len(raw)), patch.object(generator, "urlopen", return_value=io.BytesIO(raw)):
                with self.assertRaises(generator.GenerationError):
                    generator.generate(generator.DEFAULT_PROMPT)

    def test_redirects_never_forward_authorization(self):
        handler = generator._NoRedirect()
        self.assertIsNone(handler.redirect_request(None, None, 302, "", {}, "https://other.example"))

    def test_empty_default_ca_store_uses_optional_certifi(self):
        context = Mock()
        context.cert_store_stats.return_value = {"x509_ca": 0}
        certifi = SimpleNamespace(where=lambda: "/test/ca-bundle.pem")
        with patch.object(generator.ssl, "create_default_context", return_value=context), patch.dict(sys.modules, {"certifi": certifi}):
            self.assertIs(generator._tls_context(), context)
        context.load_verify_locations.assert_called_once_with(cafile="/test/ca-bundle.pem")

    def test_explicit_ca_overrides_and_populated_store_are_preserved(self):
        for override in ({"SSL_CERT_FILE": "/chosen/ca.pem"}, {"SSL_CERT_DIR": "/chosen/certs"}, {"SSL_CERT_FILE": ""}):
            with self.subTest(override=override):
                context = Mock()
                context.cert_store_stats.return_value = {"x509_ca": 0}
                with patch.dict(os.environ, override), patch.object(generator.ssl, "create_default_context", return_value=context):
                    generator._tls_context()
                context.load_verify_locations.assert_not_called()
        context = Mock()
        context.cert_store_stats.return_value = {"x509_ca": 1}
        with patch.object(generator.ssl, "create_default_context", return_value=context):
            generator._tls_context()
        context.load_verify_locations.assert_not_called()

    def test_absent_certifi_keeps_normal_verification_enabled(self):
        with patch.dict(sys.modules, {"certifi": None}):
            context = generator._tls_context()
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)


if __name__ == "__main__":
    unittest.main()
