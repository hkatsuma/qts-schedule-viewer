# Collector 開発

`src/collectors/cron.py` の collect(now) は Collection を返す。Collector は収集だけを担当し、HTTP や HTML に依存しない。Task の enabled は true / false / null、Schedule.type は拡張可能、duration_seconds は根拠がある場合だけ設定する。

| Collector | 対応状況 |
|---|---|
| cron | 標準5フィールド、リスト・範囲・間隔、英語月/曜日名。croniterで計算。QTS実機未検証 |
| power / raid / smart / snapshot / hbs | 未対応・実機調査待ち |
| security / updates / qpkg | 未対応・実機調査待ち |

コメント行と環境変数行はタスクにしない。コメントアウトされた設定は無効なジョブと推定しない。通常の crontab 行は有効として扱う。@reboot、秒・年フィールド、L/W/#/ランダム等の拡張は未対応。TZ / CRON_TZ があるファイルでは、適用範囲や QTS 実装を推定せずタスクの時刻計算を停止し部分取得として表示する。設定が全件不正でも「タスクなし」にはしない。

次回予定の探索は最大8年。見つからなければ警告し、予定を作らない。月末・隔週等の別形式は、Schedule.type を追加して実装する余地を残しており、現時点で対応済みとはしない。実行時間・履歴は収集しない。

Collector 追加時はまず docs/qts-research.md にバージョン・実際の取得元・権限・安全な匿名化サンプルを記録する。取得可能性を確定してから、新しい Collector とパーサのテストを追加し、CollectionService に登録する。失敗が他 Collector へ波及しないようにし、秘密を含む例外本文を返さない。存在しないアプリと取得失敗を別の状態にする。未確認のコマンド名一致で重複を統合しない。

cron Collector は、解析可能な設定に runs_per_active_day（通常24時間の実行対象日の回数）を付与する。これは分フィールドの候補数×時フィールドの候補数であり、実行履歴や月間の合計回数ではない。実行対象日の月日・曜日条件は予定を計算するときに保持する。
