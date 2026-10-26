# QNAP と server-a への配置・Tailnet 公開

## 採用する構成

- **QNAP**：Container Station / Docker で QSV を実行する。収集・キャッシュ・API・Web UI を同じコンテナに置く。QNAP で Tailscale は動かさない。
- **server-a**：既存の Tailscale 参加ホスト。リバースプロキシで Tailnet からの要求を受け、LAN 経由で QNAP の QSV へ転送する。ブラウザ向け HTTPS はここで終端する。
- **開発 PC**：QNAP のディレクトリをマウントしてコードを編集する。コンテナ実行ホストではない。

```text
ブラウザ ── Tailnet / HTTPS ── server-a ── LAN ── QNAP / QSV
                               プロキシ・TLS           収集・API・Web UI
```

外部公開するのは server-a の Tailnet 側入口だけとする。QNAP のバックエンド入口はプロキシ専用で、一般の LAN 端末には開放しない。新しい Tailscale ノードや、QNAP 設定の server-a への共有は不要。

## 現行ファイルとの差分

**今回はドキュメントの訂正だけを行っている。以下の設定ファイルは旧構成用であり、新構成の導入にそのまま使わない。**

| ファイル | 現在の前提 | 次の実装で必要な変更 |
|---|---|---|
| compose.yaml | ホストポートなし、外部 qsv_backend ネットワーク | QNAP の指定 LAN IP・専用ポートでバックエンドを提供する構成へ変更 |
| .env.example | 共有 Docker ネットワーク名を指定 | QNAP の bind IP・ポート等を追加し、不要な共有ネットワーク設定を整理 |
| deploy/admin.compose.override.yaml | 同一 Docker ホストの Tailscale に qsv_backend を追加 | 別ホスト間には使えないため廃止または置換 |
| deploy/Caddyfile.qsv.example | upstream が Docker サービス名 qsv:8000 | server-a 上の配置に合わせ、QNAP の LAN IP・専用ポートを upstream にする |

同名の Docker bridge network は異なるホスト間で共有されない。既存 `nas-a-admin` は構成の参考であり、その配置ホストや稼働状況を参照ディレクトリだけで断定しない。server-a の実際のプロキシが Caddy かどうかも確認してから設定を作る。

## QNAP 側の設計

`/etc/config/crontab` 1ファイルを読み取り専用 bind mount する。非 root UID/GID 10001 を基本とし、capabilities 全削除、privileged・Docker socket 不使用、root filesystem 読み取り専用を維持する。パスは Docker が動く **QNAP 側のパス**。NAS のタイムゾーンを QSV_TIMEZONE に明示する。

QTS 側の設定やファイル権限は変更しない。読み取れなければ権限不足として表示する。既存の参照可能なグループがある場合のみ GID を合わせ、Web プロセスを root にして解消しない。

バックエンドは QNAP の特定 LAN IP と未使用の専用 TCP ポートを使用する。例として `192.168.0.1:18080 → コンテナ:8000` のようなマッピングを設計するが、IP・ポートは実測して決定する。これは設定値の例であり現行 Compose の設定ではない。

- `0.0.0.0` や全 IPv6 アドレスへの無条件の公開を避ける。
- QNAP の localhost だけへの bind では、別ホストの server-a から接続できない。
- LAN IP への bind だけでは接続元は制限できない。バックエンドポートへは server-a の実際の送信元 IP のみ許可する。
- 接続制限は既存の NAS 管理機構や上位ネットワークを使い、QSV 自身が QTS の firewall 設定を書き換える機能は作らない。安全に制限できる経路を確保するまで公開しない。

Docker の公開ポートには独自の NAT / firewall 規則が関与する。QNAP の firewall 製品や Container Station で送信元制限が期待どおり効くかは未確認。任意の iptables コマンドや Docker daemon の全体設定変更を導入手順に含めず、実機の経路を確認して方法を決める。[Docker のポート公開](https://docs.docker.com/engine/network/port-publishing/) と [firewall の説明](https://docs.docker.com/engine/network/packet-filtering-firewalls/) を参照。

## server-a 側の設計

既存 Tailscale の実行形態とリバースプロキシの配置を確認する。プロキシがホスト上かコンテナ内か、Tailscale とネットワーク名前空間を共有するかは未確認であり、既存方式に合わせる。

- upstream は `http://<QNAP の LAN IP>:<専用ポート>` を基本案とする。`qsv:8000`、`127.0.0.1:8000`、QNAP の管理画面ポートには向けない。
- ブラウザ向けリスナーを既存の Tailnet 専用入口に追加し、ACL / Grants で利用者を制限する。LAN やインターネットへの入口を増やさず、Funnel は使わない。
- Tailnet IP に直接 bind する方式なら、その IP がプロキシの名前空間に存在することを確認する。userspace モードでこの方式が使えると推定しない。
- HTTPS は既存の証明書・ドメインの運用に合わせる。証明書の検証を無効化したり、端末で警告を無視したりする運用は採らない。
- アプリの手動再取得時の Origin 検査が成立するよう、元の Host を保持する。プロキシ用サブドメインまたは専用ポートのルート `/` 配下で公開する。現状の UI は絶対パスを使うため、`/qsv/` 配下への配置は未対応。
- LAN 側の実際の送信元 IP を確認する。コンテナ / NAT / 複数 NIC により server-a の想定 IP と異なる場合がある。

Tailnet の暗号化は server-a までで、LAN 側 HTTP の盗聴や改ざんを防がない。HTTP は信頼できる LAN と接続制限を前提とする。共有 LAN や信頼できない経路を通る場合は、バックエンドも証明書検証つき HTTPS 等で保護する。HTTPS だけでは送信元制限の代わりにはならない。

## 実装前に確認する情報

| 項目 | 状態 |
|---|---|
| QNAP の LAN IP / 未使用ポート / Docker バージョン | 未確認 |
| server-a から QNAP への経路と送信元 IP | 未確認 |
| バックエンドポートに有効な送信元制限の方式 | 未確認 |
| server-a のプロキシ製品・配置・Tailscale モード | 未確認 |
| ブラウザ向けドメイン・証明書・ACL / Grants | 未確認 |
| LAN 区間を HTTP にできる信頼境界 | 未確認 |

IP は DHCP 予約等で安定させる。IP アドレス制限は server-a とその LAN を信頼する前提であり、強い接続元認証が必要な環境では mTLS 等を検討する。

## 実機での検証

1. QNAP のマウント元・権限・タイムゾーン、Compose の bind IP とポートを確認する。
2. server-a の実際のプロキシ実行環境から QNAP の `/healthz` と画面へ接続できることを確認する。
3. 許可していない LAN 端末から QNAP のバックエンドへ直接接続できないことを確認する。IPv6、別 NIC、コンテナの直接ルーティング経路も確認する。
4. 許可された Tailnet 端末から HTTPS で閲覧・手動再取得・CSV 出力でき、証明書が信頼できることを確認する。
5. ACL で許可されていない Tailnet 端末から接続できないこと、Tailnet を切った端末から server-a の LAN IP と公開 IP の入口へ接続できないことを確認する。
6. ルーターのポート転送、既存 proxy、Funnel 等が入口を一般公開していないことを確認する。
7. cron の収集結果を QTS の設定と照合する。空と失敗が区別され、設定変更が再取得で反映されることを確認する。
8. QNAP と server-a をそれぞれ再起動し、アプリ・proxy・Tailscale・接続制限が復旧することを確認する。片方の停止が他方の管理機能へ影響しないことも確認する。

独自認証がないため、Tailnet の入口制御と LAN バックエンドの送信元制限の両方が成立することを公開条件とする。実機検証は未実施。

## ファイル更新時の注意

単一ファイルの bind mount は、QTS が rename により設定ファイルを置換すると古い inode を参照し続ける可能性がある。更新方法は実機未確認。反映されない場合は QNAP 上でコンテナを再作成してマウントを確認する。`/etc/config` 全体の共有で回避しない。

## 更新・停止・削除の方針

新構成の Compose を実装・確認した後、QNAP 上でアプリをビルド・更新する。server-a では QSV 向けのプロキシ設定だけを追加・更新し、Tailscale ノードを新設しない。

削除時は server-a の QSV 向けルートを除去し、QNAP のアプリと専用ポートの公開を停止する。追加した専用接続ルールだけを整理し、既存サービスの設定・Tailscale state・証明書・QTS 設定を削除しない。実行コマンドは新構成の実装後に確定する。
