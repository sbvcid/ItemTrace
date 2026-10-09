"""搜尋行為（SPEC-v1 §7）。

v1 用 `LIKE '%q%'`，不用 FTS5 —— §7.2 實測 FTS5 的 `trigram` 查不到兩字
中文、`unicode61` 不切中文，而資料量在數千筆以內全表掃描夠快。

這些測試直接打 Repository，因為它是 API 與 CLI 共用的那一層。
"""

from __future__ import annotations

import pytest

from shop.ids import normalize_identifier


@pytest.fixture()
def stocked(repo):
    """兩件商品，各帶多筆識別碼。"""
    board = repo.create_item(
        name="ROG STRIX B650E-F",
        brand="華碩",
        model="B650E-F",
        category="主機板",
        notes="含原廠風扇與 I/O 背板",
        attributes={"記憶體": "64GB", "插槽": 4},
    )
    gpu = repo.create_item(
        name="GeForce RTX 4070 Ti SUPER",
        brand="NVIDIA",
        model="RTX 4070 Ti SUPER",
        category="顯示卡",
        notes="二手，盒裝齊全",
    )
    repo.add_identifier(board.id, "BX-807 06_1234")
    repo.add_identifier(board.id, "BX-807 06_1234", kind="imei")
    repo.add_identifier(board.id, "6LWMF1234567", kind="barcode")
    repo.add_identifier(gpu.id, "6LWMF7654321")
    return {"board": board, "gpu": gpu}


def ids_found(items) -> list[str]:
    return [item.id for item in items]


# ----------------------------------------------------------------------
# §7.3 搜尋範圍：items 的文字欄位
# ----------------------------------------------------------------------


def test_search_by_name(repo, stocked):
    assert ids_found(repo.list_items(q="B650E")) == [stocked["board"].id]


def test_search_by_two_chinese_characters(repo, stocked):
    """這是選 LIKE 不選 FTS5 的唯一理由：兩字中文必須找得到。"""
    assert ids_found(repo.list_items(q="主機")) == [stocked["board"].id]
    assert ids_found(repo.list_items(q="顯示")) == [stocked["gpu"].id]


def test_search_by_brand(repo, stocked):
    assert ids_found(repo.list_items(q="華碩")) == [stocked["board"].id]
    assert ids_found(repo.list_items(q="NVIDIA")) == [stocked["gpu"].id]


def test_search_by_model(repo, stocked):
    assert ids_found(repo.list_items(q="RTX 4070")) == [stocked["gpu"].id]


def test_search_by_category(repo, stocked):
    assert ids_found(repo.list_items(q="主機板")) == [stocked["board"].id]


def test_search_by_notes(repo, stocked):
    assert ids_found(repo.list_items(q="原廠風扇")) == [stocked["board"].id]
    assert ids_found(repo.list_items(q="盒裝齊全")) == [stocked["gpu"].id]


def test_search_by_attributes_json(repo, stocked):
    """§7.3：attributes 以字串比對，所以 JSON 裡的字與數字都找得到。"""
    assert ids_found(repo.list_items(q="64GB")) == [stocked["board"].id]
    assert ids_found(repo.list_items(q="插槽")) == [stocked["board"].id]


def test_search_matches_substring_anywhere(repo, stocked):
    assert ids_found(repo.list_items(q="STRIX")) == [stocked["board"].id]


def test_search_is_case_insensitive_for_ascii(repo, stocked):
    assert ids_found(repo.list_items(q="b650e")) == [stocked["board"].id]
    assert ids_found(repo.list_items(q="nvidia")) == [stocked["gpu"].id]


# ----------------------------------------------------------------------
# §7.1 identifier 搜尋
# ----------------------------------------------------------------------


def test_search_by_identifier_normalized(repo, stocked):
    """搜尋端也做正規化，所以帶分隔符的存值能被半截命中。"""
    assert ids_found(repo.list_items(q="807061234")) == [stocked["board"].id]


def test_search_by_identifier_is_case_insensitive(repo, stocked):
    """兩件商品都有 6LWMF 開頭的序號，小寫查詢兩件都要命中。"""
    assert set(ids_found(repo.list_items(q="6lwmf"))) == {
        stocked["board"].id,
        stocked["gpu"].id,
    }


def test_search_by_identifier_with_separators_in_query(repo, stocked):
    assert ids_found(repo.list_items(q="BX-807 06")) == [stocked["board"].id]


def test_search_matches_raw_identifier_value(repo, stocked):
    """value 欄位也納入範圍，帶空格的原始寫法要能直接命中。"""
    assert ids_found(repo.list_items(q="BX-807 06_1234")) == [stocked["board"].id]


def test_item_with_several_matching_identifiers_appears_once(repo, stocked):
    """同一商品有多筆命中的識別碼時，只能出現一次。"""
    found = repo.list_items(q="807061234")
    assert ids_found(found) == [stocked["board"].id]
    assert len(found) == 1


def test_item_found_only_through_identifier(repo, stocked):
    """識別碼命中、欄位都沒關鍵字的商品也要找得到。"""
    repo.create_item(name="無名商品")
    assert ids_found(repo.list_items(q="6LWMF7654321")) == [stocked["gpu"].id]


def test_search_normalization_matches_spec_examples(repo):
    """§7.1 的實測表。"""
    item = repo.create_item(name="測試件")
    repo.add_identifier(item.id, "BX-807 06_1234")
    assert ids_found(repo.list_items(q="807061234")) == [item.id]
    assert ids_found(repo.list_items(q="bx-807-061234")) == [item.id]


def test_normalized_query_is_what_matches_not_the_raw_one(repo):
    """查詢字串兩邊都正規化：raw query 不會誤中。"""
    item = repo.create_item(name="測試件")
    repo.add_identifier(item.id, "BX807061234")
    assert ids_found(repo.list_items(q="807061234")) == [item.id]
    assert normalize_identifier("bx-807 061234") == "BX807061234"


# ----------------------------------------------------------------------
# 空查詢與無結果
# ----------------------------------------------------------------------


def test_no_query_returns_everything(repo, stocked):
    assert len(repo.list_items()) == 2


def test_blank_query_is_ignored(repo, stocked):
    """全空白的 q 不該變成「搜尋空字串」而撈出全部。"""
    assert len(repo.list_items(q="   ")) == 2
    assert len(repo.list_items(q="")) == 2
    assert len(repo.list_items(q=None)) == 2


def test_query_with_no_match_returns_empty(repo, stocked):
    assert repo.list_items(q="根本不存在的字串") == []


def test_query_with_no_match_still_respects_paging(repo, stocked):
    assert repo.list_items(q="不存在", limit=5, offset=2) == []


# ----------------------------------------------------------------------
# 搜尋 + 篩選
# ----------------------------------------------------------------------


def test_search_combined_with_status_filter(repo, stocked):
    repo.void_item(stocked["board"].id)
    assert ids_found(repo.list_items(q="華碩", status="active")) == []
    assert ids_found(repo.list_items(q="華碩", status="void")) == [stocked["board"].id]


def test_search_combined_with_category_filter(repo, stocked):
    """兩件都有 6LWMF 開頭的序號，category 決定命中誰。"""
    assert ids_found(repo.list_items(q="6LWMF", category="顯示卡")) == [stocked["gpu"].id]
    assert ids_found(repo.list_items(q="6LWMF", category="主機板")) == [stocked["board"].id]
    assert repo.list_items(q="6LWMF", category="固態硬碟") == []


def test_search_combined_with_both_filters(repo, stocked):
    repo.void_item(stocked["board"].id)
    assert ids_found(repo.list_items(q="6LWMF", status="void", category="主機板")) == [
        stocked["board"].id
    ]
    assert repo.list_items(q="6LWMF", status="active", category="主機板") == []


def test_search_combined_with_pagination(repo, stocked):
    for index in range(5):
        repo.create_item(name=f"同款主機板 {index}", category="主機板")
    first = repo.list_items(q="主機板", limit=2)
    second = repo.list_items(q="主機板", limit=2, offset=2)
    assert len(first) == len(second) == 2
    assert not {item.id for item in first} & {item.id for item in second}


def test_status_filter_without_search_still_works(repo, stocked):
    repo.void_item(stocked["gpu"].id)
    assert ids_found(repo.list_items(status="void")) == [stocked["gpu"].id]
    assert ids_found(repo.list_items(status="active")) == [stocked["board"].id]


def test_voided_item_is_findable_without_a_status_filter(repo, stocked):
    """目前的行為：沒有指定 status 時，void 的商品一樣會被搜尋到。

    這是刻意的 —— 搜尋是「你還在嗎」的工具，不是日常清單。日常清單才會
    預設排除 void。
    """
    repo.void_item(stocked["board"].id)
    assert ids_found(repo.list_items(q="華碩")) == [stocked["board"].id]


# ----------------------------------------------------------------------
# lookup_identifiers（只查識別碼）
# ----------------------------------------------------------------------


def test_lookup_finds_partial_serial(repo, stocked):
    """主機板有兩筆識別碼正規化成同一組，回兩列是正確的。"""
    found = repo.lookup_identifiers("807061234")
    assert {row.item_id for row in found} == {stocked["board"].id}
    assert sorted(row.kind for row in found) == ["imei", "serial"]


def test_lookup_returns_all_matches_not_just_first(repo, stocked):
    found = repo.lookup_identifiers("6LWMF")
    assert {row.item_id for row in found} == {stocked["board"].id, stocked["gpu"].id}


def test_lookup_can_filter_by_kind(repo, stocked):
    assert len(repo.lookup_identifiers("6LWMF", kind="barcode")) == 1
    assert repo.lookup_identifiers("6LWMF", kind="imei") == []


def test_lookup_ignores_items_field_names(repo, stocked):
    """lookup 只查識別碼；品名關鍵字不該出現在結果裡。"""
    assert repo.lookup_identifiers("華碩") == []


def test_lookup_normalizes_the_query(repo, stocked):
    assert repo.lookup_identifiers("bx-807 061234")
    assert repo.lookup_identifiers("BX807061234")


def test_lookup_with_no_match(repo, stocked):
    assert repo.lookup_identifiers("ZZZZZZZZ") == []


def test_lookup_respects_limit(repo):
    item = repo.create_item(name="大量序號")
    for index in range(10):
        repo.add_identifier(item.id, f"SAME-SHARED-{index}")
    assert len(repo.lookup_identifiers("SAME-SHARED")) == 10
    assert len(repo.lookup_identifiers("SAME-SHARED", limit=3)) == 3


# ----------------------------------------------------------------------
# Phase 2B：曾被接受過的舊詮釋詞彙仍可搜尋
# ----------------------------------------------------------------------


def test_previously_accepted_terms_remain_searchable(repo):
    """新詮釋取代舊欄位值後，被取代的詞彙（曾被接受）仍找得到。"""
    item = repo.create_item()
    accepted = repo.add_suggestion(item.id, "name", "Makita 電鑽")
    repo.accept_suggestion(accepted.id)
    assert repo.get_item(item.id).name == "Makita 電鑽"

    repo.update_item(item.id, {"name": "牧田 18V 震動電鑽"})
    assert [row.id for row in repo.list_items(q="Makita")] == [item.id]
    assert [row.id for row in repo.list_items(q="牧田")] == [item.id]
    assert [row.id for row in repo.list_items(q="電鑽")] == [item.id]


def test_unconfirmed_guesses_are_not_searchable(repo):
    """pending / rejected / superseded 都是未經確認的猜測，不進搜尋。"""
    item = repo.create_item()

    repo.add_suggestion(item.id, "brand", "PENDING-GUESS-1")
    assert repo.list_items(q="PENDING-GUESS-1") == []

    rejected = repo.add_suggestion(item.id, "model", "REJECTED-1")
    repo.reject_suggestion(rejected.id)
    assert repo.list_items(q="REJECTED-1") == []

    repo.add_suggestion(item.id, "condition", "SUPERSEDED-1")
    repo.replace_pending_suggestions(item.id, [], model_name="t")
    assert repo.list_items(q="SUPERSEDED-1") == []