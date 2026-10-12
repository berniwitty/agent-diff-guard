# Evaluation (v0.1)

> After this evaluation ADG001's default severity was changed from `error` to `warn`
> because of its 8.0% false-positive rate. The numbers below were measured with it at
> `error`; severity does not change what a rule detects.

Corpus: 300 commits, the 100 most recent non-merge commits that change both Python source
and Python tests in each of [httpx](https://github.com/encode/httpx),
[pydantic](https://github.com/pydantic/pydantic) and [rich](https://github.com/Textualize/rich),
pinned in [`eval/commits.txt`](../eval/commits.txt). Each original commit is a negative;
[`eval/inject.py`](../eval/inject.py) plants one shortcut per rule on top of it for the
positives. Reproduce with `make eval-repos eval-commits eval` (or the `uv run python -m eval.*`
commands in the README).

| Rule | Severity | Injected | Detected | Recall | Originals flagged | FP rate |
|---|---|---|---|---|---|---|
| ADG001 | error | 300 | 297 | 99% | 24 | 8.0% ⚠ |
| ADG002 | error | 300 | 300 | 100% | 2 | 0.7% |
| ADG003 | error | 300 | 298 | 99% | 11 | 3.7% |
| ADG004 | warn | 23 | 23 | 100% | 1 | 0.3% |
| ADG010 | error | 300 | 300 | 100% | 0 | 0.0% |
| ADG011 | error | 300 | 300 | 100% | 0 | 0.0% |
| ADG012 | warn | 300 | 300 | 100% | 3 | 1.0% |
| ADG020 | warn | 300 | 299 | 100% | 38 | 12.7% |
| ADG021 | error | 200 | 200 | 100% | 2 | 0.7% |
| ADG030 | warn | 300 | 300 | 100% | 0 | 0.0% |
| ADG040 | info | 0 | 0 | n/a | 0 | 0.0% |
| ADG099 | warn | 300 | 300 | 100% | 0 | 0.0% |

**False-positive rate** is the share of the 300 original, upstream-reviewed commits on which
the rule reported anything. **Recall** is measured on injected shortcuts, which are more
canonical than the shortcuts real agents take, so it is an optimistic upper bound.
"Injected" counts commits where the rule's mutation applied (ADG004 needs an existing
assertion whose call the commit modified; ADG021 needs coverage or ruff config, or a CI
workflow). ADG040 needs a coverage run per commit and is not evaluated.

## Against the v0.1 target (FP ≤ 5% for `error` rules)

| Rule | FP rate | Target |
|---|---|---|
| ADG001 test-removed | 8.0% | **missed** |
| ADG002 test-skipped | 0.7% | met |
| ADG003 assertion-weakened | 3.7% | met |
| ADG010 stub-body | 0.0% | met |
| ADG011 hardcoded-test-value | 0.0% | met |
| ADG021 gate-loosened | 0.7% | met |

### ADG001: why it misses, and what was tried
The 24 flagged commits are honest test removals of two kinds:

1. **The feature went away with its tests**: deprecations removed (httpx
   "escalate deprecations", "Drop mode argument"), support dropped (pydantic "Remove
   support for `eval_type_backport()`"), behaviour reverted.
2. **Tests rewritten or consolidated**: the same behaviour checked with different values
   or in a new layout (pydantic Fraction tests moved, rich markdown tests replaced, httpx
   URL percent-encoding tests reorganised).

Both are exactly what a reviewer should look at, but SPEC counts every finding on an
upstream commit as a false positive.

One refinement was tried and **rejected**: not reporting a removed test that references a
name (definition or parameter) the same diff removed from the code. It only lowered the
rate to 7.0%, and it cost recall (99% → 98%), because generic names such as `url`,
`text` or `padding` disappear in ordinary refactors and then explain away real
deletions. Tuning it further against this same corpus would be overfitting, so the rule is
reported as measured above.

One refinement made *before* this run did hold up: a removed test only counts as
renamed or moved when the new test also checks mostly the same values. The injector
showed that "delete a test and add a similar-looking test of other values" was otherwise
missed.

### Other findings on original commits
- **ADG003 (11 commits)**: lower assertion counts in refactors, often alongside a removed
  feature. This is the "fewer assertions" false-positive category documented in
  [ADG003](rules/ADG003.md).
- **ADG002 (2 commits)**: version-specific `skipif` / `pytest.skip`, a documented
  false-positive category.
- **ADG021 (2 commits)**: real gate loosenings (httpx added ruff ignores `B028`/`B904`;
  pydantic added a per-file `UP007` ignore). Correct detections, counted as FP by the
  metric.
- **ADG020 (warn, 38 commits)**: real suppressions added upstream, mostly
  `# pragma: no cover` / `nocover`, `# noqa: UP007|UP035|B018` and `# type: ignore`. The rule
  is `warn` because these are often justified.
- **ADG004 (warn, 1 commit)**, **ADG012 (warn, 3 commits)**: listed below.

## Findings on original commits

Each is either a rule bug or a real shortcut found in the wild.

- `httpx@1805ee0d22f9` `httpx/_api.py:23` warn ADG020: Added a `# pragma: no cover` suppression comment.
- `httpx@1805ee0d22f9` `httpx/_client.py:56` warn ADG020: Added a `# pragma: no cover` suppression comment.
- `httpx@1805ee0d22f9` `httpx/_urls.py:404` warn ADG020: Added a `# pragma: nocover` suppression comment.
- `httpx@1805ee0d22f9` `tests/test_config.py` error ADG001: Test `test_SSLContext_repr` was removed.
- `httpx@1805ee0d22f9` `tests/test_config.py` error ADG001: Test `test_certifi_lazy_loading` was removed.
- `httpx@e9cabc8e1deb` `httpx/_main.py:24` warn ADG020: Added a `# pragma: no cover` suppression comment.
- `httpx@e9cabc8e1deb` `httpx/_transports/default.py:34` warn ADG020: Added a `# pragma: no cover` suppression comment.
- `httpx@e9cabc8e1deb` `httpx/_transports/default.py:36` warn ADG020: Added a `# pragma: no cover` suppression comment.
- `httpx@8e36f2bc685d` `httpx/_config.py:30` warn ADG020: Added a `# pragma: nocover` suppression comment.
- `httpx@8e36f2bc685d` `httpx/_decoders.py:20` warn ADG020: Added a `# pragma: no cover` suppression comment.
- `httpx@8e36f2bc685d` `httpx/_decoders.py:32` warn ADG020: Added a `# pragma: no cover` suppression comment.
- `httpx@8e36f2bc685d` `httpx/_decoders.py:33` warn ADG020: Added a `# type: ignore` suppression comment.
- `httpx@8e36f2bc685d` `httpx/_transports/asgi.py:38` warn ADG020: Added a `# pragma: nocover` suppression comment.
- `httpx@8e36f2bc685d` `httpx/_transports/default.py:142` warn ADG020: Added a `# pragma: nocover` suppression comment.
- `httpx@8e36f2bc685d` `httpx/_transports/default.py:288` warn ADG020: Added a `# pragma: nocover` suppression comment.
- `httpx@8e36f2bc685d` `tests/client/test_proxies.py` error ADG001: Test `test_proxies_parameter` was removed.
- `httpx@8e36f2bc685d` `tests/client/test_proxies.py` error ADG001: Test `test_socks_proxy_deprecated` was removed.
- `httpx@8e36f2bc685d` `tests/client/test_proxies.py` error ADG001: Test `test_unsupported_proxy_scheme_deprecated` was removed.
- `httpx@8e36f2bc685d` `tests/client/test_proxies.py` error ADG001: Test `test_proxy_and_proxies_together` was removed.
- `httpx@8e36f2bc685d` `tests/client/test_proxies.py:87` error ADG003: Test `test_transport_for_request` has fewer assertions than before (5 -> 4).
- `httpx@8e36f2bc685d` `tests/client/test_proxies.py:103` error ADG003: Test `test_async_proxy_close` has fewer assertions than before (1 -> 0).
- `httpx@8e36f2bc685d` `tests/client/test_proxies.py:113` error ADG003: Test `test_sync_proxy_close` has fewer assertions than before (1 -> 0).
- `httpx@8e36f2bc685d` `tests/client/test_proxies.py:249` error ADG003: Test `test_for_deprecated_proxy_params` has fewer assertions than before (2 -> 1).
- `httpx@8e36f2bc685d` `tests/models/test_url.py` error ADG001: Test `test_url_raw_compatibility` was removed.
- `httpx@8e36f2bc685d` `tests/test_asgi.py` error ADG001: Test `test_deprecated_shortcut` was removed.
- `httpx@8e36f2bc685d` `tests/test_config.py` error ADG001: Test `test_load_ssl_config_verify_non_existing_path` was removed.
- `httpx@8e36f2bc685d` `tests/test_config.py` error ADG001: Test `test_load_ssl_config_verify_env_file` was removed.
- `httpx@8e36f2bc685d` `tests/test_config.py` error ADG001: Test `test_load_ssl_context` was removed.
- `httpx@8e36f2bc685d` `tests/test_config.py` error ADG001: Test `test_ssl_config_support_for_keylog_file` was removed.
- `httpx@8e36f2bc685d` `tests/test_utils.py` error ADG001: Test `test_logging_ssl` was removed.
- `httpx@8e36f2bc685d` `tests/test_utils.py` error ADG001: Test `test_get_ssl_cert_file` was removed.
- `httpx@8e36f2bc685d` `tests/test_wsgi.py` error ADG001: Test `test_deprecated_shortcut` was removed.
- `httpx@49d74a2e7f77` `tests/client/test_headers.py:185` warn ADG020: Added a `# type: ignore` suppression comment.
- `httpx@392dbe45f086` `httpx/_compat.py:35` warn ADG020: Added a `# type: ignore[union-attr]` suppression comment.
- `httpx@392dbe45f086` `httpx/_decoders.py:153` warn ADG020: Added a `# pragma: no cover` suppression comment.
- `httpx@392dbe45f086` `httpx/_decoders.py:177` warn ADG020: Added a `# pragma: no cover` suppression comment.
- `httpx@392dbe45f086` `httpx/_decoders.py:371` warn ADG020: Added a `# pragma: no cover` suppression comment.
- `httpx@4f6edf36e93f` `tests/test_utils.py:83` error ADG003: Test `test_parse_header_links` replaced an exact assertion with a weaker check.
- `httpx@a11fc3849b94` `tests/models/test_url.py` error ADG001: Test `test_path_percent_encoding` was removed.
- `httpx@a11fc3849b94` `tests/models/test_url.py` error ADG001: Test `test_query_percent_encoding` was removed.
- `httpx@a11fc3849b94` `tests/models/test_url.py` error ADG001: Test `test_fragment_percent_encoding` was removed.
- `httpx@a11fc3849b94` `tests/models/test_url.py` error ADG001: Test `test_url_with_url_encoded_path` was removed.
- `httpx@1e110964736a` `httpx/_decoders.py:285` warn ADG020: Added a `# pragma: no cover` suppression comment.
- `httpx@1e110964736a` `httpx/_models.py:856` warn ADG020: Added a `# pragma: no cover` suppression comment.
- `httpx@1e110964736a` `httpx/_models.py:960` warn ADG020: Added a `# pragma: no cover` suppression comment.
- `httpx@88e84314378b` `tests/test_auth.py:116` warn ADG020: Added a `# pragma: no cover` suppression comment.
- `httpx@15d09a3bbc20` `httpx/_utils.py:467` warn ADG012: Added `except:` handler that silently discards the error.
- `httpx@15d09a3bbc20` `httpx/_utils.py:475` warn ADG012: Added `except:` handler that silently discards the error.
- `httpx@daec2bdcdb96` `pyproject.toml:97` error ADG021: Added ruff ignore `B028`.
- `httpx@daec2bdcdb96` `pyproject.toml:97` error ADG021: Added ruff ignore `B904`.
- `httpx@daec2bdcdb96` `tests/client/test_async_client.py:87` warn ADG020: Added a `# noqa: B018` suppression comment.
- `httpx@daec2bdcdb96` `tests/models/test_requests.py:108` warn ADG020: Added a `# noqa: B018` suppression comment.
- `httpx@daec2bdcdb96` `tests/models/test_requests.py:204` warn ADG020: Added a `# noqa: B018` suppression comment.
- `httpx@daec2bdcdb96` `tests/models/test_requests.py:221` warn ADG020: Added a `# noqa: B018` suppression comment.
- `httpx@daec2bdcdb96` `tests/models/test_responses.py:751` warn ADG020: Added a `# noqa: B018` suppression comment.
- `httpx@daec2bdcdb96` `tests/models/test_responses.py:912` warn ADG020: Added a `# noqa: B018` suppression comment.
- `httpx@daec2bdcdb96` `tests/models/test_responses.py:955` warn ADG020: Added a `# noqa: B018` suppression comment.
- `httpx@daec2bdcdb96` `tests/test_exceptions.py:56` warn ADG020: Added a `# noqa: B018` suppression comment.
- `httpx@f1157dbc4102` `tests/test_utils.py` error ADG001: Test `test_logs_debug` was removed.
- `httpx@f1157dbc4102` `tests/test_utils.py` error ADG001: Test `test_logs_trace` was removed.
- `httpx@f1157dbc4102` `tests/test_utils.py` error ADG001: Test `test_logs_redirect_chain` was removed.
- `httpx@85c5898d8e48` `tests/test_decoders.py:228` warn ADG004: Expected value changed from `['a\n', '\n', 'b\n']` to `['a', '', 'b']` while `decode` was modified.
- `httpx@85c5898d8e48` `tests/test_decoders.py:233` warn ADG004: Expected value changed from `['a\n', '\n', 'b\n', 'c\n']` to `['a', '', 'b', 'c']` while `decode` was modified.
- `httpx@85c5898d8e48` `tests/test_decoders.py:239` warn ADG004: Expected value changed from `['12345\n']` to `['12345']` while `decode` was modified.
- `httpx@85c5898d8e48` `tests/test_decoders.py:242` warn ADG004: Expected value changed from `['foo bar baz\n']` to `['foo bar baz']` while `decode` was modified.
- `httpx@85c5898d8e48` `tests/test_decoders.py:249` warn ADG004: Expected value changed from `['a\n', '\n', 'b\n']` to `['a', '', 'b']` while `decode` was modified.
- `httpx@85c5898d8e48` `tests/test_decoders.py:254` warn ADG004: Expected value changed from `['a\n', '\n', 'b\n']` to `['a', '', 'b']` while `decode` was modified.
- `httpx@85c5898d8e48` `tests/test_decoders.py:255` warn ADG004: Expected value changed from `['c\n']` to `['c']` while `flush` was modified.
- `httpx@85c5898d8e48` `tests/test_decoders.py:261` warn ADG004: Expected value changed from `['12345\n']` to `['12345']` while `decode` was modified.
- `httpx@85c5898d8e48` `tests/test_decoders.py:264` warn ADG004: Expected value changed from `['c']` to `['foo bar baz']` while `flush` was modified.
- `httpx@85c5898d8e48` `tests/test_decoders.py:270` warn ADG004: Expected value changed from `['a\n', '\n', 'b\n']` to `['a', '', 'b']` while `decode` was modified.
- `httpx@85c5898d8e48` `tests/test_decoders.py:275` warn ADG004: Expected value changed from `['a\n', '\n', 'b\n', 'c\n']` to `['a', '', 'b', 'c']` while `decode` was modified.
- `httpx@85c5898d8e48` `tests/test_decoders.py:281` warn ADG004: Expected value changed from `['a\n', '\n', 'b\n']` to `['a', '', 'b']` while `decode` was modified.
- `httpx@85c5898d8e48` `tests/test_decoders.py:287` warn ADG004: Expected value changed from `['12345\n']` to `['12345']` while `decode` was modified.
- `httpx@85c5898d8e48` `tests/test_decoders.py:290` warn ADG004: Expected value changed from `['foo bar baz\n']` to `['foo bar baz']` while `decode` was modified.
- `httpx@f0fd91925bc8` `httpx/_transports/mock.py:20` warn ADG020: Added a `# pragma: no cover` suppression comment.
- `httpx@f0fd91925bc8` `tests/client/test_auth.py:713` warn ADG020: Added a `# type: ignore[return-value]` suppression comment.
- `httpx@f0fd91925bc8` `tests/client/test_redirects.py:349` warn ADG020: Added a `# type: ignore[return-value]` suppression comment.
- `httpx@59914c769057` `tests/client/test_auth.py` error ADG001: Test `test_auth_header_has_priority_over_netrc` was removed.
- `httpx@59914c769057` `tests/client/test_auth.py` error ADG001: Test `test_trust_env_auth` was removed.
- `httpx@59914c769057` `tests/client/test_auth.py:276` warn ADG020: Added a `# pragma: no cover` suppression comment.
- `httpx@59914c769057` `tests/client/test_auth.py:299` warn ADG020: Added a `# pragma: no cover` suppression comment.
- `httpx@59914c769057` `tests/test_utils.py` error ADG001: Test `test_bad_get_netrc_login` was removed.
- `httpx@59914c769057` `tests/test_utils.py` error ADG001: Test `test_get_netrc_login` was removed.
- `httpx@59914c769057` `tests/test_utils.py` error ADG001: Test `test_get_netrc_unknown` was removed.
- `httpx@57daabf67370` `tests/models/test_url.py:311` error ADG003: Test `test_url_copywith_security` has fewer assertions than before (18 -> 2).
- `httpx@bddd774ce065` `tests/models/test_queryparams.py` error ADG001: Test `test_invalid_query_params` was removed.
- `httpx@a8dd079be702` `tests/test_content.py:364` warn ADG020: Added a `# type: ignore` suppression comment.
- `httpx@69e13cbc393e` `httpx/_config.py:129` warn ADG020: Added a `# pragma: no cover` suppression comment.
- `httpx@69e13cbc393e` `httpx/_status_codes.py:28` warn ADG020: Added a `# type: ignore[attr-defined]` suppression comment.
- `httpx@1b4e7fbb4825` `httpx/_auth.py:13` warn ADG020: Added a `# pragma: no cover` suppression comment.
- `httpx@1b4e7fbb4825` `httpx/_transports/mock.py:32` warn ADG020: Added a `# type: ignore[func-returns-value,assignment]` suppression comment.
- `httpx@0ebe9259aca9` `tests/test_multipart.py` error ADG001: Test `test_multipart_encode_files_raises_exception_with_str_content` was removed.
- `httpx@1c33a2854e5d` `tests/models/test_responses.py:233` error ADG003: Test `test_response_no_charset_with_iso_8859_1_content` has fewer assertions than before (3 -> 2).
- `httpx@1c33a2854e5d` `tests/models/test_responses.py:247` error ADG003: Test `test_response_no_charset_with_cp_1252_content` has fewer assertions than before (3 -> 2).
- `httpx@3350d7e6831e` `tests/client/test_async_client.py:349` warn ADG020: Added a `# pragma: nocover` suppression comment.
- `httpx@420911bc693e` `httpx/_models.py:1588` warn ADG020: Added a `# pragma: nocover` suppression comment.
- `httpx@420911bc693e` `httpx/_models.py:1686` warn ADG020: Added a `# pragma: nocover` suppression comment.
- `httpx@8dc9b6bd5911` `httpx/_transports/default.py:159` warn ADG020: Added a `# noqa` suppression comment.
- `httpx@8dc9b6bd5911` `httpx/_transports/default.py:160` warn ADG020: Added a `# pragma: nocover` suppression comment.
- `httpx@8dc9b6bd5911` `httpx/_transports/default.py:181` warn ADG020: Added a `# pragma: nocover` suppression comment.
- `httpx@8dc9b6bd5911` `httpx/_transports/default.py:294` warn ADG020: Added a `# noqa` suppression comment.
- `httpx@8dc9b6bd5911` `httpx/_transports/default.py:295` warn ADG020: Added a `# pragma: nocover` suppression comment.
- `httpx@7f0d43daad60` `tests/client/test_async_client.py` error ADG001: Test `test_deleting_unclosed_async_client_causes_warning` was removed.
- `httpx@0f1ff50a1e88` `httpx/_multipart.py:92` warn ADG020: Added a `# type: ignore` suppression comment.
- `httpx@6f5865f8605b` `httpx/_content.py:55` warn ADG020: Added a `# type: ignore` suppression comment.
- `httpx@6f5865f8605b` `httpx/_content.py:58` warn ADG020: Added a `# type: ignore` suppression comment.
- `httpx@6f5865f8605b` `httpx/_content.py:80` warn ADG020: Added a `# type: ignore` suppression comment.
- `httpx@6f5865f8605b` `httpx/_content.py:83` warn ADG020: Added a `# type: ignore` suppression comment.
- `httpx@6f5865f8605b` `tests/test_content.py:76` warn ADG020: Added a `# pragma: nocover` suppression comment.
- `httpx@61188feeaec5` `httpx/_main.py:179` warn ADG020: Added a `# pragma: nocover` suppression comment.
- `httpx@61188feeaec5` `httpx/_main.py:206` warn ADG020: Added a `# pragma: nocover` suppression comment.
- `httpx@61188feeaec5` `httpx/_main.py:221` warn ADG020: Added a `# pragma: nocover` suppression comment.
- `httpx@61188feeaec5` `httpx/_main.py:227` warn ADG020: Added a `# pragma: nocover` suppression comment.
- `httpx@61188feeaec5` `httpx/_transports/default.py:109` warn ADG020: Added a `# type: ignore` suppression comment.
- `httpx@61188feeaec5` `httpx/_transports/default.py:213` warn ADG020: Added a `# type: ignore` suppression comment.
- `httpx@61188feeaec5` `tests/test_exceptions.py:28` error ADG003: Test `test_httpcore_exception_mapping` has fewer assertions than before (3 -> 2).
- `httpx@ee9250d60bc5` `httpx/__init__.py:48` warn ADG020: Added a `# pragma: nocover` suppression comment.
- `httpx@ee9250d60bc5` `httpx/__init__.py:50` warn ADG020: Added a `# type: ignore` suppression comment.
- `httpx@ee9250d60bc5` `httpx/_main.py:99` warn ADG020: Added a `# pragma: nocover` suppression comment.
- `httpx@ee9250d60bc5` `httpx/_main.py:101` warn ADG020: Added a `# pragma: nocover` suppression comment.
- `httpx@ee9250d60bc5` `httpx/_main.py:160` warn ADG020: Added a `# pragma: nocover` suppression comment.
- `httpx@ee9250d60bc5` `httpx/_main.py:166` warn ADG020: Added a `# pragma: nocover` suppression comment.
- `httpx@ee9250d60bc5` `httpx/_main.py:185` warn ADG020: Added a `# type: ignore` suppression comment.
- `httpx@ee9250d60bc5` `httpx/_main.py:201` warn ADG020: Added a `# pragma: nocover` suppression comment.
- `httpx@ee9250d60bc5` `httpx/_main.py:214` warn ADG020: Added a `# pragma: nocover` suppression comment.
- `httpx@ee9250d60bc5` `httpx/_main.py:416` warn ADG020: Added a `# type: ignore` suppression comment.
- `httpx@ff9813e84dab` `httpx/_types.py:100` warn ADG020: Added a `# pragma: nocover` suppression comment.
- `httpx@ff9813e84dab` `httpx/_types.py:101` warn ADG020: Added a `# pragma: nocover` suppression comment.
- `httpx@ff9813e84dab` `httpx/_types.py:140` warn ADG020: Added a `# pragma: nocover` suppression comment.
- `httpx@ff9813e84dab` `httpx/_types.py:141` warn ADG020: Added a `# pragma: nocover` suppression comment.
- `httpx@ff9813e84dab` `tests/client/test_redirects.py:316` error ADG003: Test `test_can_stream_if_no_redirect` has fewer assertions than before (3 -> 2).
- `httpx@2d9c3580e077` `httpx/_client.py:1599` warn ADG020: Added a `# pragma: no cover` suppression comment.
- `httpx@927c88d34f73` `tests/client/test_async_client.py:275` warn ADG020: Added a `# pragma: nocover` suppression comment.
- `httpx@927c88d34f73` `tests/client/test_client.py:316` warn ADG020: Added a `# pragma: nocover` suppression comment.
- `httpx@d5143120d10f` `httpx/_compat.py:20` warn ADG020: Added a `# pragma: nocover` suppression comment.
- `httpx@d5143120d10f` `httpx/_decoders.py:98` warn ADG020: Added a `# pragma: nocover` suppression comment.
- `httpx@acb5e6ac500f` `tests/models/test_responses.py` error ADG001: Test `test_json_without_specified_encoding_decode_error` was removed.
- `httpx@acb5e6ac500f` `tests/models/test_responses.py` error ADG001: Test `test_json_without_specified_encoding_value_error` was removed.
- `httpx@77246617ca6b` `tests/test_config.py` error ADG001: Test `test_invalid_proxy_mode` was removed.
- `httpx@77246617ca6b` `tests/test_config.py:213` error ADG003: Test `test_proxy_from_url` has fewer assertions than before (4 -> 3).
- `httpx@20e66d204864` `tests/test_multipart.py:242` warn ADG020: Added a `# type: ignore` suppression comment.
- `httpx@20e66d204864` `tests/test_multipart.py:250` warn ADG020: Added a `# type: ignore` suppression comment.
- `pydantic@c821eaccf987` `tests/test_type_adapter.py` error ADG001: Test `test_ta_config_used_for_json_schemas` was removed.
- `pydantic@027b5c714791` `tests/test_forward_ref.py:1765` warn ADG020: Added a `# noqa: F821` suppression comment.
- `pydantic@027b5c714791` `tests/test_forward_ref.py:1768` warn ADG020: Added a `# noqa: F841` suppression comment.
- `pydantic@e5b02608847e` `tests/test_types_zoneinfo.py` error ADG001: Deleted test file removed 3 test(s).
- `pydantic@dae3788547fa` `tests/test_config.py:1026` warn ADG020: Added a `# noqa: F821` suppression comment.
- `pydantic@617abdb1bb95` `tests/types/test_counter.py` error ADG001: Test `test_typing_coercion_counter` was removed.
- `pydantic@4a66dc2fec70` `pydantic/experimental/missing_sentinel.py:28` warn ADG020: Added a `# pragma: no cover` suppression comment.
- `pydantic@831893ed0411` `tests/test_freethreaded.py:122` warn ADG020: Added a `# noqa: F821` suppression comment.
- `pydantic@78a5c4c6e27e` `tests/typechecking/type_adapter.py:31` warn ADG020: Added a `# noqa: UP007` suppression comment.
- `pydantic@78a5c4c6e27e` `tests/typechecking/type_adapter.py:36` warn ADG020: Added a `# type: ignore[arg-type, var-annotated]` suppression comment.
- `pydantic@78a5c4c6e27e` `tests/typechecking/type_adapter.py:37` warn ADG020: Added a `# type: ignore[assert-type, valid-type]` suppression comment.
- `pydantic@78a5c4c6e27e` `tests/typechecking/type_adapter.py:38` warn ADG020: Added a `# type: ignore[assert-type, valid-type]` suppression comment.
- `pydantic@78a5c4c6e27e` `tests/typechecking/type_form.py:16` warn ADG020: Added a `# type: ignore[arg-type]` suppression comment.
- `pydantic@6b470f4cfabb` `tests/test_missing_sentinel.py:203` warn ADG020: Added a `# noqa: UP007` suppression comment.
- `pydantic@6b470f4cfabb` `tests/test_missing_sentinel.py:207` warn ADG020: Added a `# noqa: UP007` suppression comment.
- `pydantic@5283870ccfce` `pydantic-core/tests/validators/test_decimal.py` error ADG001: Test `test_validate_max_digits_and_decimal_places_edge_case` was removed.
- `pydantic@c5af60286356` `pydantic/_internal/_validators.py:438` warn ADG020: Added a `# noqa: F821` suppression comment.
- `pydantic@c5af60286356` `pydantic/_internal/_validators.py:439` warn ADG020: Added a `# noqa: F821` suppression comment.
- `pydantic@c5af60286356` `tests/types/test_defaultdict.py:50` warn ADG020: Added a `# noqa: F821` suppression comment.
- `pydantic@af0e0a6a3288` `pydantic-core/tests/test_docstrings.py:32` error ADG002: Test `test_docstrings` now calls `pytest.skip`.
- `pydantic@41b1a85dd74a` `pydantic-core/python/pydantic_core/core_schema.py:1630` warn ADG020: Added a `# noqa: UP007` suppression comment.
- `pydantic@41b1a85dd74a` `pydantic-core/python/pydantic_core/core_schema.py:2036` warn ADG020: Added a `# noqa: UP007` suppression comment.
- `pydantic@111c942fa87f` `pydantic/_internal/_fields.py:14` warn ADG020: Added a `# noqa: UP035` suppression comment.
- `pydantic@111c942fa87f` `tests/test_private_attributes.py:638` warn ADG020: Added a `# noqa: F841` suppression comment.
- `pydantic@53b39c38c062` `tests/test_types_namedtuple.py` error ADG001: Deleted test file removed 1 test(s).
- `pydantic@b75fadbaa55d` `tests/test_typing.py` error ADG001: Test `test_is_none_type` was removed.
- `pydantic@92208bf84df1` `tests/test_types.py` error ADG001: Test `test_fraction_validation` was removed.
- `pydantic@92208bf84df1` `tests/test_types.py` error ADG001: Test `test_fraction_validation_lax` was removed.
- `pydantic@92208bf84df1` `tests/test_types.py` error ADG001: Test `test_fraction_validation_strict` was removed.
- `pydantic@92208bf84df1` `tests/test_types.py` error ADG001: Test `test_fraction_serialization` was removed.
- `pydantic@92208bf84df1` `tests/test_types.py` error ADG001: Test `test_fraction_json_schema` was removed.
- `pydantic@92208bf84df1` `tests/types/test_fraction.py` error ADG001: Test `test_fraction_validation_error_non_strict` was removed.
- `pydantic@92208bf84df1` `tests/types/test_fraction.py:45` error ADG003: Test `test_fraction` has fewer assertions than before (2 -> 1).
- `pydantic@92208bf84df1` `tests/types/test_fraction.py:114` error ADG003: Test `test_fraction_validation_error_strict` has fewer assertions than before (2 -> 1).
- `pydantic@7974d591c7d2` `pydantic/mypy.py:267` warn ADG020: Added a `# noqa: T201` suppression comment.
- `pydantic@7974d591c7d2` `pydantic/mypy.py:277` warn ADG020: Added a `# noqa: T201` suppression comment.
- `pydantic@8a1a222b6013` `pydantic/_internal/_typing_extra.py:471` warn ADG020: Added a `# pragma: no cover` suppression comment.
- `pydantic@8a1a222b6013` `tests/test_forward_ref.py` error ADG001: Test `test_recursive_models_union_backport` was removed.
- `pydantic@8a1a222b6013` `tests/test_main.py` error ADG001: Test `test_eval_type_backport` was removed.
- `pydantic@8a1a222b6013` `tests/test_type_adapter.py` error ADG001: Test `test_eval_type_backport` was removed.
- `pydantic@8a1a222b6013` `tests/test_types_namedtuple.py` error ADG001: Test `test_eval_type_backport` was removed.
- `pydantic@8a1a222b6013` `tests/test_typing.py` error ADG001: Test `test_eval_type_backport_not_installed` was removed.
- `pydantic@8a1a222b6013` `tests/test_validate_call.py` error ADG001: Test `test_eval_type_backport` was removed.
- `pydantic@b36eaeb4e5ee` `pydantic-core/tests/test_misc.py:6` warn ADG020: Added a `# noqa: UP035` suppression comment.
- `pydantic@b36eaeb4e5ee` `pydantic-core/tests/test_schema_functions.py:7` warn ADG020: Added a `# noqa: UP035` suppression comment.
- `pydantic@b36eaeb4e5ee` `pydantic/_internal/_core_utils.py:8` warn ADG020: Added a `# noqa: UP035` suppression comment.
- `pydantic@b36eaeb4e5ee` `pydantic/_internal/_forward_ref.py:20` warn ADG020: Added a `# noqa: UP007` suppression comment.
- `pydantic@b36eaeb4e5ee` `pydantic/_internal/_forward_ref.py:23` warn ADG020: Added a `# noqa: UP007` suppression comment.
- `pydantic@b36eaeb4e5ee` `pydantic/_internal/_generate_schema.py:53` warn ADG020: Added a `# noqa: UP035` suppression comment.
- `pydantic@b36eaeb4e5ee` `pydantic/_internal/_generate_schema.py:2124` warn ADG020: Added a `# noqa: UP007` suppression comment.
- `pydantic@b36eaeb4e5ee` `pydantic/_internal/_model_construction.py:17` warn ADG020: Added a `# noqa: UP035` suppression comment.
- `pydantic@b36eaeb4e5ee` `pydantic/_internal/_typing_extra.py:17` warn ADG020: Added a `# noqa: UP035` suppression comment.
- `pydantic@b36eaeb4e5ee` `pydantic/_internal/_validators.py:21` warn ADG020: Added a `# noqa: UP035` suppression comment.
- `pydantic@b36eaeb4e5ee` `pydantic/types.py:31` warn ADG020: Added a `# noqa: UP035` suppression comment.
- `pydantic@b36eaeb4e5ee` `pyproject.toml:249` error ADG021: Added ruff per-file ignore `UP007` for `pydantic/deprecated/*`.
- `pydantic@b36eaeb4e5ee` `tests/test_edge_cases.py:31` warn ADG020: Added a `# noqa: UP035` suppression comment.
- `pydantic@b36eaeb4e5ee` `tests/test_edge_cases.py:1647` warn ADG020: Added a `# noqa: UP045` suppression comment.
- `pydantic@b36eaeb4e5ee` `tests/test_edge_cases.py:1649` warn ADG020: Added a `# noqa: UP007` suppression comment.
- `pydantic@b36eaeb4e5ee` `tests/test_edge_cases.py:1650` warn ADG020: Added a `# noqa: UP007` suppression comment.
- `pydantic@b36eaeb4e5ee` `tests/test_edge_cases.py:1653` warn ADG020: Added a `# noqa: UP007` suppression comment.
- `pydantic@b36eaeb4e5ee` `tests/test_edge_cases.py:1658` warn ADG020: Added a `# noqa: UP045` suppression comment.
- `pydantic@b36eaeb4e5ee` `tests/test_forward_ref.py:10` warn ADG020: Added a `# noqa: UP035` suppression comment.
- `pydantic@b36eaeb4e5ee` `tests/test_forward_ref.py:80` error ADG002: Test `test_basic_forward_ref` gained a `pytest.mark.skipif` marker.
- `pydantic@b36eaeb4e5ee` `tests/test_forward_ref.py:100` error ADG002: Test `test_self_forward_ref_module` gained a `pytest.mark.skipif` marker.
- `pydantic@b36eaeb4e5ee` `tests/test_forward_ref.py:193` error ADG002: Test `test_forward_ref_sub_types` gained a `pytest.mark.skipif` marker.
- `pydantic@b36eaeb4e5ee` `tests/test_forward_ref.py:1682` warn ADG020: Added a `# noqa: UP007` suppression comment.
- `pydantic@b36eaeb4e5ee` `tests/test_generics.py:25` warn ADG020: Added a `# noqa: UP035` suppression comment.
- `pydantic@b36eaeb4e5ee` `tests/test_generics.py:1069` warn ADG020: Added a `# noqa: UP007` suppression comment.
- `pydantic@b36eaeb4e5ee` `tests/test_generics.py:1070` warn ADG020: Added a `# noqa: UP007` suppression comment.
- `pydantic@b36eaeb4e5ee` `tests/test_generics.py:1156` warn ADG020: Added a `# noqa: UP045` suppression comment.
- `pydantic@b36eaeb4e5ee` `tests/test_main.py` error ADG001: Test `test_new_union_origin` was removed.
- `pydantic@b36eaeb4e5ee` `tests/test_model_signature.py:8` warn ADG020: Added a `# noqa: UP035` suppression comment.
- `pydantic@b36eaeb4e5ee` `tests/test_type_adapter.py:54` warn ADG020: Added a `# noqa: UP007` suppression comment.
- `pydantic@b36eaeb4e5ee` `tests/test_type_adapter.py:55` warn ADG020: Added a `# noqa: UP007` suppression comment.
- `pydantic@b36eaeb4e5ee` `tests/test_types.py` error ADG001: Test `test_typing_extension_literal_field` was removed.
- `pydantic@b36eaeb4e5ee` `tests/test_types.py:47` warn ADG020: Added a `# noqa: UP035` suppression comment.
- `pydantic@b36eaeb4e5ee` `tests/test_types.py:146` warn ADG020: Added a `# noqa: UP045` suppression comment.
- `pydantic@b36eaeb4e5ee` `tests/test_types.py:6229` warn ADG020: Added a `# noqa: F821` suppression comment.
- `pydantic@b36eaeb4e5ee` `tests/test_types.py:7079` warn ADG020: Added a `# noqa: UP007` suppression comment.
- `pydantic@b36eaeb4e5ee` `tests/test_types.py:7083` warn ADG020: Added a `# noqa: UP007` suppression comment.
- `pydantic@b36eaeb4e5ee` `tests/test_utils.py` error ADG001: Test `test_display_as_type_310` was removed.
- `pydantic@b36eaeb4e5ee` `tests/test_utils.py:66` warn ADG020: Added a `# noqa: UP007` suppression comment.
- `pydantic@b36eaeb4e5ee` `tests/test_utils.py:74` warn ADG020: Added a `# noqa: UP007` suppression comment.
- `pydantic@b36eaeb4e5ee` `tests/test_utils.py:397` warn ADG020: Added a `# noqa: UP007` suppression comment.
- `rich@f924a21a3144` `rich/_unicode_data/__init__.py:10` warn ADG020: Added a `# pragma: no cover` suppression comment.
- `rich@82afcb4ff58d` `tests/test_console.py` error ADG001: Test `test_no_nested_live` was removed.
- `rich@a3b27a3aba6d` `tests/test_console.py:1026` error ADG003: Test `test_capture_and_record` has fewer assertions than before (4 -> 2).
- `rich@f6eca21a9b39` `tests/test_syntax.py:331` error ADG003: Test `test_from_path_unknown_lexer` has fewer assertions than before (2 -> 1).
- `rich@d9eff2aa4450` `tests/test_repr.py:75` warn ADG012: Added `except Exception:` handler that silently discards the error.
- `rich@5e26525befd4` `tests/test_pretty.py` error ADG001: Test `test_ipy_display_hook__classes_to_not_render` was removed.
- `rich@090523e73436` `rich/_fileno.py:19` warn ADG012: Added `except Exception:` handler that silently discards the error.
- `rich@873cb7970568` `tests/test_null_file.py:4` error ADG003: Test `test_null_file` has fewer assertions than before (20 -> 17).
- `rich@02dffcf9cfe0` `tests/test_pretty.py` error ADG001: Test `test_recursive` was removed.
- `rich@ffe9ae82f669` `tests/test_console.py` error ADG001: Test `test_no_stdout_file` was removed.
- `rich@9383774fd980` `tests/test_markdown.py` error ADG001: Test `test_simple_markdown` was removed.
- `rich@9383774fd980` `tests/test_markdown.py` error ADG001: Test `test_simple_markdown_2` was removed.
- `rich@9383774fd980` `tests/test_markdown.py` error ADG001: Test `test_markdown_table` was removed.
- `rich@9383774fd980` `tests/test_markdown.py` error ADG001: Test `test_md_3` was removed.
