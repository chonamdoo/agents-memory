from agents_memory.lexical import tokens


def test_hangul_bigrams_do_not_cross_word_or_sentence_boundaries():
    values = tokens("메모리 검색. 정정 후 철회")
    assert {"메모리", "메모", "모리", "검색", "정정", "철회"}.issubset(values)
    assert "리검" not in values
    assert "색정" not in values
    assert "후철" not in values


def test_original_code_names_and_components_are_searchable():
    values = tokens("getHTTPResponse cache_limit_v2 src/memory_store.py")
    assert {
        "getHTTPResponse", "gethttpresponse", "get", "HTTP", "http", "Response", "response",
        "cache_limit_v2", "cache", "limit", "v", "2", "src/memory_store.py", "memory", "store",
    }.issubset(values)
    assert "cachelimit" not in values


def test_search_nfkc_keeps_original_tokens_without_rewriting_evidence():
    original = "ＡＰＩ＿Ｖ２ 설정"
    values = tokens(original)
    assert "ＡＰＩ＿Ｖ２" in values
    assert "API_V2" in values
    assert "api_v2" in values


def test_decomposed_hangul_has_normalized_search_bigrams():
    values = tokens("메모리")
    assert "메모리" in values
    assert {"메모리", "메모", "모리"}.issubset(values)


def test_identifiers_do_not_join_across_korean_or_punctuation_boundaries():
    values = tokens("설정 cache_limit, getValue() 이후")
    assert "cache_limit" in values
    assert "getValue" in values
    assert "limitget" not in values
    assert "설정cache_limit" not in values


def test_oversized_code_and_query_tokens_are_dropped_without_losing_small_components():
    values = tokens("a" * 4096 + " valid_identifier " + "a" * 1500 + ".CacheLimit")
    assert "valid_identifier" in values
    assert "CacheLimit" in values
    assert all(len(value.encode("utf-8")) <= 1024 for value in values)


def test_unicode_and_casefold_expansion_obey_utf8_token_size():
    values = tokens("가" * 1024 + " İ" * 400 + " " + "İ" * 512)
    assert "가가" in values
    assert all(len(value.encode("utf-8")) <= 1024 for value in values)


def test_token_count_is_bounded_and_order_is_deterministic():
    text = " ".join(f"identifier_{index}" for index in range(4096))
    first = tokens(text)
    assert len(first) == 2048
    assert first == tokens(text)
    assert len(set(first)) == len(first)
