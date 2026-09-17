"""ツール関数群（第 2 章 2.6 ツール設計 7 原則）。

- docstring は LLM への説明書: 1 行目がツール全体、Args に具体例
- エラーは例外ではなく {"status": "error", ...} の dict で返す
- 冪等: 同じ呼び出しを繰り返しても安全
- 1 ツール 1 責務、戻り値は必ず status を持つ dict
- tool_context 引数はスキーマに出ず ADK が注入する（State / Artifact / 認証）

ここでは学習用のモック実装。本番では API / DB 呼び出しに置き換える。
"""

from __future__ import annotations

from typing import Optional

from google.adk.tools import ToolContext
from google.genai import types

from .state_keys import StateKeys, get_max_results

# モックデータ（本番では削除）
_ITEMS: dict[str, dict] = {
    "ITEM-001": {"id": "ITEM-001", "name": "ワイヤレスマウス", "price": 3980, "stock": 12, "category": "周辺機器"},
    "ITEM-002": {"id": "ITEM-002", "name": "USB-C ハブ", "price": 5480, "stock": 0, "category": "周辺機器"},
    "ITEM-003": {"id": "ITEM-003", "name": "メカニカルキーボード", "price": 12800, "stock": 5, "category": "入力機器"},
}
_RECORDS: dict[str, dict] = {
    "REC-100": {"id": "REC-100", "owner": "user-001", "status": "active", "note": "初期データ"},
}


def search_items(query: str, category: Optional[str] = None, tool_context: ToolContext = None) -> dict:
    """商品をキーワードで検索する。

    Args:
        query: 検索キーワード（例: "マウス", "キーボード"）
        category: 絞り込むカテゴリ（例: "周辺機器"）。省略時は全カテゴリ

    Returns:
        status と results（商品リスト）を含む辞書。該当なしでも status は success
    """
    limit = get_max_results(tool_context.state) if tool_context is not None else 5
    if tool_context is not None:
        count = int(tool_context.state.get(StateKeys.TEMP_SEARCH_COUNT, 0)) + 1
        tool_context.state[StateKeys.TEMP_SEARCH_COUNT] = count

    results = [
        item
        for item in _ITEMS.values()
        if query in item["name"] and (category is None or item["category"] == category)
    ]
    return {"status": "success", "query": query, "results": results[:limit], "total": len(results)}


def get_record(record_id: str) -> dict:
    """レコードの詳細を取得する。

    Args:
        record_id: レコード ID。"REC-" で始まる英数字（例: REC-100）

    Returns:
        status と record を含む辞書。見つからない場合は status="error"
    """
    if not record_id.startswith("REC-"):
        return {"status": "error", "error": f"レコード ID の形式が不正です: {record_id}（例: REC-100）"}
    record = _RECORDS.get(record_id)
    if record is None:
        return {"status": "error", "error": f"レコード '{record_id}' が見つかりません。"}
    return {"status": "success", "record": record}


def update_record(record_id: str, note: str) -> dict:
    """レコードの備考を更新する（冪等: 同じ内容なら変更なしで success）。

    Args:
        record_id: 更新対象のレコード ID（例: REC-100）
        note: 新しい備考（例: "顧客確認済み"）

    Returns:
        status / message / record を含む辞書
    """
    record = _RECORDS.get(record_id)
    if record is None:
        return {"status": "error", "error": f"レコード '{record_id}' が見つかりません。"}
    if record["note"] == note:
        return {"status": "success", "message": "すでに同じ内容です。変更はありません。", "record": record}
    record["note"] = note
    return {"status": "success", "message": f"レコード {record_id} の備考を更新しました。", "record": record}


async def delete_record(record_id: str, reason: str, tool_context: ToolContext) -> dict:
    """レコードを削除する（不可逆。before_tool_callback の権限チェック / HITL 承認の対象）。

    Args:
        record_id: 削除対象のレコード ID（例: REC-100）
        reason: 削除理由（例: "重複データのため"）

    Returns:
        status / message / artifact_version を含む辞書。削除済みなら success（冪等）
    """
    if record_id not in _RECORDS:
        return {"status": "success", "message": f"レコード {record_id} はすでに削除済みです。", "warning": "取り消しはできません。"}
    del _RECORDS[record_id]
    # 監査用に削除記録を Artifact として保存（save_artifact はコルーチン）
    part = types.Part.from_text(text=f"削除記録\nID: {record_id}\n理由: {reason}\n")
    version = await tool_context.save_artifact(filename=f"delete_{record_id}.txt", artifact=part)
    return {
        "status": "success",
        "message": f"レコード {record_id} を削除しました。",
        "warning": "この操作は取り消せません。",
        "artifact_version": version,
    }
