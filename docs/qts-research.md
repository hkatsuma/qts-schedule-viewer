# QTS 調査状況

## 配置の前提（2026-10-26 訂正）

利用者の確認により、QNAP では Tailscale は動いていない。QSV は QNAP 上のコンテナで動かし、Tailnet に参加している server-a がリバースプロキシする設計とする。server-a の実際のプロキシ製品・配置・IP・証明書・ACL は未確認。

## 参照ファイルから確認できたこと

2026-10-25、開発 PC からマウントした `/mnt/iscsi/containers/nas-a-admin` の README、compose.yaml、Caddyfile を読み取り確認した。`.env` の秘密値や secrets・Tailscale state の内容は調査対象にしない。

- Tailscale コンテナと Caddy コンテナがある。
- Caddy は `network_mode: service:tailscale` を使用する。
- Caddy は Tailscale の証明書取得と既存サービスへの reverse_proxy を設定している。
- TS_USERSPACE・TS_DEST_IP・TS_SERVE_CONFIG の明示設定は compose と環境設定内で確認できなかった。カーネル / userspace の実際のモードは未確認。QNAP 上に Tailnet IP があることの根拠にはならない。
- これらは設定ファイルの観測であり、配置ホストや現在の稼働・到達性の確認ではない。参照ディレクトリが QNAP 上の稼働サービスを意味するという以前の前提は撤回する。
- 開発環境自身に `/etc/config/crontab` はない。QNAP の設定ファイルはまだ観測できていない。

## 収集対象

| 収集対象 | 取得方式 | 権限 | 対応可否 | 注意事項 |
|---|---|---|---|---|
| cron | SPEC 記載の /etc/config/crontab | 実機の所有者・モード要確認 | 標準5フィールドを実装、実機未検証 | 読み取り専用の単一ファイルマウント |
| 電源 | 未確認 | 未確認 | 未対応 | 保存方式を実機で確認する |
| RAID | 未確認 | 未確認 | 未対応 | cronコマンド名だけで同定しない |
| SMART | 未確認 | 未確認 | 未対応 | 同上 |
| Snapshot | 未確認 | 未確認 | 未対応 | 内部DBの形式を推測しない |
| HBS 3 | 未確認 | 未確認 | 未対応 | 資格情報を含むDB全体を共有しない |
| セキュリティ・更新・QPKG | 未確認 | 未確認 | 未対応 | インストール有無も未判定 |

QTS バージョン、CPU アーキテクチャ、Container Station / QPKG のバージョンも未確認。サポート確認済み QTS バージョンはまだない。samples/crontab は人工データであり実機観測の証拠ではない。

## 実機で次に確認する事項

QNAP 上で `uname -m` と `docker version`、`docker compose version` を参照し、QTS と Container Station のバージョンは管理画面で確認する。`ls -l /etc/config/crontab` で必要権限を確認する。crontab の内容を共有する場合はコマンド引数やパスに含まれる秘密値をローカルで除去する。

電源・ストレージ・Snapshot・HBS 3 は管理画面の設定と保存情報を読み取りで照合する。機密データがあるディレクトリ全体のコピーや再帰探索を初手にしない。公開済みの参照 API の有無を確認し、なければ実際に観測したファイル形式・QTS/QPKG バージョン・匿名化サンプル・権限を記録したうえで Collector を追加する。

公開方式については server-a のリバースプロキシと Tailscale の実行形態、QNAP への LAN 到達性、実際の送信元 IP、バックエンドポートの接続制限を確認する。別ホスト間の経路なので Docker の同名ネットワークによる接続は採用しない。

本稿に記した crontab のパスは SPEC 由来、既存の公開構成はローカルファイル観測由来。QTS 内部 API / DB に関する推測は採用していない。
