---
name: example-skill
description: 注文に関する問い合わせに対応する。注文状況の確認、キャンセル、配送追跡を扱う。（LLM がスキル選択に使う。対応範囲を具体的に）
metadata:
  version: "1.0.0"
---

# 注文管理スキル

## 対応範囲
- 注文状況の確認、キャンセル、配送追跡

## 対応手順
1. ユーザーから注文 ID（`ORD-` で始まる英数字）を確認する
2. `get_order_status` ツールで注文情報を取得し、ステータスに応じて回答する
3. キャンセル依頼は `references/cancel-policy.md` を参照し、条件を満たす場合のみ `cancel_order` を呼ぶ

## 注意事項
- キャンセルは取り消し不可であることを必ず伝える
- 本文で言及するツール名（`get_order_status` / `cancel_order`）は、エージェントの `tools=` に登録した関数名と一致させる（Python ツールはスキル内に置かない）
