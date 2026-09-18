"""ツール関数（モック実装）の契約テスト: status 必須・0 件時はモデル向けのヒントを返す。"""

from my_agent.tools import get_record, search_items


class TestSearchItems:
    def test_hit_returns_results_without_hint(self):
        result = search_items("マウス")
        assert result["status"] == "success"
        assert result["total"] == 1
        assert result["results"][0]["id"] == "ITEM-001"
        assert "message" not in result

    def test_no_hit_returns_bounded_retry_hint(self):
        """0 件は success のままだが、モデルが再検索を繰り返さないよう次の行動を message で示す。"""
        result = search_items("ノートパソコン")
        assert result["status"] == "success"
        assert result["results"] == []
        assert result["total"] == 0
        assert "再検索" in result["message"]
        assert "1 回" in result["message"]

    def test_category_filter(self):
        assert search_items("マウス", category="入力機器")["total"] == 0
        assert search_items("マウス", category="周辺機器")["total"] == 1


class TestGetRecord:
    def test_invalid_id_format_is_error_dict(self):
        assert get_record("100")["status"] == "error"

    def test_missing_record_is_error_dict(self):
        assert "見つかりません" in get_record("REC-999")["error"]
