# QTS 調査状況

## 配置と取得方式

QSV は QNAP 上のコンテナで収集・API・Web UI を動かす。QNAP では Tailscale を使わない。server-a 上の QSV 専用 Tailscale コンテナと Caddy が、専用ノード名の443で受けて QNAP へ LAN HTTP で転送する。入口は既存 tag:www-server の grants、バックエンドは実接続元 IP allowlist で制限する。

公開構成の参考は `/mnt/iscsi/containers/nas-a-admin` の README、Compose、Caddyfile。Tailscale コンテナとネットワーク・socket を共有する Caddy、Tailscale からの証明書取得、LAN upstream への中継を参照した。参照ファイルの内容と実際の稼働状態は区別する。秘密値や Tailscale state の内容は調査対象にしない。

## 収集対象

| 収集対象 | 取得方式 | 権限 | 対応可否 | 注意事項 |
|---|---|---|---|---|
| cron | /etc/config/crontab の読み取り | 実機の所有者・モードは未確認 | 標準5フィールドを実装。利用者が API 応答を確認 | QTS 全設定との照合は未実施。単一ファイルの read-only mount |
| 電源 | 未確認 | 未確認 | 未対応 | 保存方式を実機で確認する |
| RAID | 未確認 | 未確認 | 未対応 | cronコマンド名だけで同定しない |
| SMART | 未確認 | 未確認 | 未対応 | 同上 |
| Snapshot | 未確認 | 未確認 | 未対応 | 内部DBの形式を推測しない |
| HBS 3 | 未確認 | 未確認 | 未対応 | 資格情報を含むDB全体を共有しない |
| セキュリティ・更新・QPKG | 未確認 | 未確認 | 未対応 | インストール有無も未判定 |

crontab のパスは仕様書由来。samples/crontab は人工データで、実機観測の証拠ではない。QTS のバージョンと CPU、Container Station / QPKG のバージョンは未確認で、バージョン別の対応保証はまだない。

## 実機で確認する事項

QNAP 上で `uname -m`、`docker version`、`docker compose version` を参照し、QTS と Container Station のバージョンは管理画面で確認する。`ls -l /etc/config/crontab` で必要権限を確認する。crontab の内容を共有する場合はコマンド引数やパスに含まれる秘密値をローカルで除去する。

電源・ストレージ・Snapshot・HBS 3 は、管理画面の設定と保存情報を読み取りで照合する。機密データがあるディレクトリ全体のコピーや再帰探索を初手にしない。公開された参照 API があれば優先し、なければ実際に観測したファイル形式・QTS/QPKG バージョン・匿名化サンプル・権限を記録して Collector を実装する。QTS 内部 API / DB の推測は実装の根拠にしない。

専用ノードの Tailnet Lock 署名・DNS 名・IP、証明書取得、NAT 後の LAN 送信元、QNAP の allowlist の有効性を確認する。稼働確認の範囲は [validation.md](validation.md)、操作手順は [deployment.md](deployment.md) を参照。
