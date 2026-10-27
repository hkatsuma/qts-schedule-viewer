# QNAP と server-a への配置・Tailnet 公開

## 採用する構成と制御の分担

```text
ブラウザ ── Tailnet / HTTPS ── server-a ── ホーム LAN / HTTP ── QNAP / QSV
             Tailscale ACL       リバースプロキシ                    プロキシ IP 制限
```

- QNAP：Container Station / Docker で収集・キャッシュ・API・Web UI を同じコンテナに置く。Tailscale は動かさない。
- server-a：QSV 専用の Tailscale コンテナと Caddy を動かし、専用ホスト名の HTTPS 443 で終端する。ホスト自身の既存 Tailscale とは別ノードとして参加する。ここへのアクセスは **Tailscale ACL** で制御し、プロキシ側に独自の IP allowlist は追加しない。
- QSV：バックエンドに直接接続する **中継プロキシの IP だけ** を allowlist で制限する。Tailnet の各クライアント IP は検査しない。
- ホーム LAN は信頼する。バックエンドは HTTP + プロキシ IP 制限とし、パスワード・トークン等の追加認証情報は使わない。
- 開発 PC：QNAP のディレクトリをマウントして編集する。コンテナ実行ホストではない。

既存 nas-a-admin の方式に合わせ、QSV 専用 Tailnet ノードを1つ登録する。QNAP の生設定ファイルの server-a への共有は不要。同名 Docker bridge network で別ホストは接続できないため、QNAP の LAN IP・専用ポートを upstream にする。

## QNAP 上での設定・起動

`/etc/config/crontab` 1ファイルを読み取り専用 bind mount する。非 root、capabilities 全削除、privileged・Docker socket 不使用、root filesystem 読み取り専用を維持する。QTS の設定やファイル権限をアプリから変更しない。読み取り権限がなければ収集状況に表示する。

QNAP のシェルで実行する。Container Station から Compose を登録する場合も QNAP 上のファイルと同じ設定値を使う。

```sh
cp .env.example .env
# 下表に従い .env を編集する
docker compose config --quiet
docker compose up -d --build
docker compose ps
docker compose logs --tail=50 qsv
```

| 環境変数 | 意味 | 設定例（実機値に置換） |
|---|---|---|
| QSV_BIND_IP | ポートを公開する QNAP の LAN IP。必須 | 192.168.0.1 |
| QSV_BIND_PORT | 未使用のバックエンド HTTP ポート | 18080 |
| QSV_ALLOWED_PROXY_IPS | QNAP から見たプロキシの接続元 IP。必須 | 192.168.0.2 |
| QSV_CRONTAB_SOURCE | QNAP 上の参照ファイル | /etc/config/crontab |
| QSV_TIMEZONE | NAS のタイムゾーン | Asia/Tokyo |
| QSV_REFRESH_SECONDS | 収集周期。最小30秒 | 300 |
| QSV_UID / QSV_GID | コンテナの非 root 実行ユーザー | 10001 / 10001 |

QSV_BIND_IP は LAN の特定アドレスにする。`0.0.0.0` や全 IPv6 への無条件の公開を避ける。localhost だけへの bind では別ホストから接続できない。IP は DHCP 予約等で安定させる。

QSV_ALLOWED_PROXY_IPS はカンマ区切りの個別 IPv4 / IPv6 アドレス。前後の空白は除去する。CIDR・ホスト名・ワイルドカード・末尾の空要素は不正として起動エラーにする。IPv4-mapped IPv6 は IPv4 と同一視する。Compose では未設定・空を設定エラーにする。アプリ単体で未設定・空の場合は全拒否になる。

例：`QSV_ALLOWED_PROXY_IPS=192.168.0.2,192.168.0.3` は2台の中継プロキシを許可する。Tailnet クライアントのアドレスを列挙する設定ではない。

設定変更後は `docker compose up -d` でコンテナを再作成する。単なる restart では変更後の環境変数は反映されない。

## IP 判定とヘルスチェック

QSV は実際の TCP 接続元を判定する。`X-Forwarded-For`、`Forwarded`、`X-Real-IP` は一切 allowlist 判定に使わない。Dockerfile の Uvicorn `--no-proxy-headers` を外さない。

許可外の接続からの画面・API・CSV・静的ファイルへの要求には **HTTP 403** を返す。アプリ層の制限であり、TCP 接続を遮断する firewall ではない。唯一の例外はコンテナ内 loopback からの `/healthz` で、Docker HEALTHCHECK のために許可する。loopback でも他の API・画面は通常の制限対象。

コンテナ / NAT / 複数 NIC により実際の接続元が想定と異なる場合がある。許可元・拒否元の両方から実測し、server-a だけを識別できることを確認する。複数の送信元が共通の gateway IP に見える場合は、その gateway を安易に許可しない。経路の見直しや既存のネットワーク制限でプロキシを区別する。

Docker と firewall の経路については [Docker のポート公開](https://docs.docker.com/engine/network/port-publishing/) と [firewall の説明](https://docs.docker.com/engine/network/packet-filtering-firewalls/) を参照。QSV が QTS の firewall を書き換える機能は持たない。

## server-a のリバースプロキシ

`deploy/Caddyfile.qsv.example` は Caddy の設定例。実際のプロキシ製品・配置・Tailscale モード・IP・ドメイン・証明書はまだ未確認であり、既存方式に合わせる。

1. upstream を `http://<QNAP の LAN IP>:<専用ポート>` にする。Docker サービス名 `qsv:8000` や server-a 自身の localhost には向けない。
2. QSV 専用ノードの443番にサイトを追加し、既存 tag:www-server の grants で利用者を制限する。独自の IP allowlist や追加の認証情報はプロキシに設けない。Funnel は使わない。
3. Tailscale は TS_USERSPACE=false のカーネルモードとし、Caddy は network_mode: service:tailscale でネットワークを共有する。新ノードの Tailnet IPv4 だけに bind する。
4. ブラウザ向け HTTPS は既存の証明書運用に合わせる。例の `get_certificate tailscale` は専用 Tailscale コンテナの socket へのアクセスが必要。
5. 元の Host を保持する。手動再取得の Origin 検査に必要。現状の UI はルート `/` 配下用なので、専用ドメインまたは専用ポートを使う。`/qsv/` のようなサブパス配置は未対応。
6. 専用 Compose だけを起動・更新する。ホスト自身の Tailscale や既存 nas-a-admin の state・設定は共有も変更もしない。

Caddy の参考：[reverse_proxy](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy)。

旧 `deploy/admin.compose.override.yaml` は同一ホスト用だったため、現在は無効な移行案内として `services: {}` のみを残している。両ホストの起動ファイルへ組み込む必要はない。

## 実機での検証

1. QNAP の bind IP・ポート・マウント・権限・タイムゾーンを確認する。
2. server-a の実際のプロキシ実行環境から QNAP の `/healthz`、画面、API が HTTP 200 になることを確認する。
3. 許可していない LAN 端末から QNAP の画面・API・CSV が HTTP 403 になることを確認する。許可 IP を X-Forwarded-For に偽装しても拒否されることを確認する。IPv6・別 NIC 経路も確認する。
4. 許可された Tailnet 端末から HTTPS で閲覧・手動再取得・CSV 出力できることを確認する。許可されない端末は Tailscale ACL で拒否されることを確認する。
5. Tailnet を切った端末から server-a の LAN IP や公開 IP で入口を利用できず、ルーターのポート転送や Funnel 等でも一般公開されていないことを確認する。
6. QTS の設定と収集結果を照合し、設定変更後の再取得も確認する。
7. 両ホストをそれぞれ再起動し、QSV・proxy・Tailscale・設定値が復旧することを確認する。

LAN 区間は HTTP であり Tailscale による暗号化の対象外。信頼するホーム LAN と許可したプロキシを前提とする。実機検証は未実施。

## ファイル更新・運用

単一ファイルの bind mount は、QTS が rename で設定を置換すると古い inode を参照し続ける可能性がある。更新方法は実機未確認。反映されない場合は QNAP 上で `docker compose up -d --force-recreate qsv` によりマウントし直す。`/etc/config` 全体の共有で回避しない。

更新は QNAP 上でコード取得後 `docker compose up -d --build`。削除時は server-a の QSV 向けサイトを除去し、QNAP で `docker compose down` を実行する。既存 Tailscale state・証明書・QTS 設定は削除しない。

## アプリ読み込み時の PermissionError

`Permission denied: '/app/src/__init__.py'` は、アプリ自身のイメージ内ファイルを非 root ユーザーが読めない起動エラー。crontab の読み取り権限不足とは別の問題である。通常の chmod だけでは、名前付きユーザーへの拒否 ACL が残る場合がある。Dockerfile はビルド用 `deploy/prepare_image.py` で、イメージ内 `/app` の POSIX アクセス ACL・ディレクトリのデフォルト ACL を除去してから、ディレクトリ0755・ファイル0644へ正規化する。所有者は COPY で root に明示する。ACL の除去に失敗した場合はビルドを止める。ビルド中に非 root ユーザーで import と静的ファイルの読み取りを検証する。QTS 側の設定ファイルや共有フォルダの権限は変更しない。

chmod のみの前回修正でも同じエラーが発生したため、ACL の除去を追加した。QNAP 実機の ACL 値は未取得であり、これが実機の原因であることは未確定。POSIX ACL とモードの相互作用は [Moby の報告](https://github.com/moby/moby/issues/49766) も参照。

修正版は Python 3.15 の公式 slim イメージを使用する。Dockerfile の修正を反映するには QNAP 上でイメージの再ビルドが必要。

```sh
docker compose build --pull --no-cache qsv
docker compose up -d --force-recreate qsv
docker compose logs --tail=50 qsv
```

再ビルド後も同じエラーが出る場合は、実際に使用している Compose プロジェクトとイメージが修正版であること、追加の override で `/app` をホストからマウントしていないことを確認する。

ログの `git was not found` はビルド時にコミット情報を付与できない警告であり、今回の PermissionError の原因ではない。

## server-a での今回の公開設定

構成は `専用 Tailscale ノード(qsv) + Caddy :443 → LAN HTTP → QNAP :18080`。ホスト server-a の8443を使う前案は撤回した。ホスト側の443/8443を Docker で公開しないので既存サービスと競合しない。

### 1. 専用ノードの初回ログイン

以下は server-a 上、本リポジトリのディレクトリで実行する。`.env.proxy` は QNAP アプリ用の `.env` と別ファイルで、Git 管理対象外。

```sh
cp deploy/.env.proxy.example deploy/.env.proxy
sudo docker compose --env-file deploy/.env.proxy -f deploy/compose.proxy.yaml config --quiet
sudo docker compose --env-file deploy/.env.proxy -f deploy/compose.proxy.yaml up -d tailscale
sudo docker compose --env-file deploy/.env.proxy -f deploy/compose.proxy.yaml logs --tail=100 tailscale
```

ログに表示される認証 URL をブラウザで開き、`tag:www-server` を付与できる管理者としてログインする。必要なら管理画面で端末を承認する。初回ログイン待ちの間は unhealthy でもよい。認証 URL を公開しない。初回だけブラウザで登録し、その後は named volume の state と TS_AUTH_ONCE=true で同じノードを使う。リポジトリに認証キーや既存サービスの state をコピーする必要はない。

### 2. 新ノードの IP と DNS 名を設定

```sh
sudo docker compose --env-file deploy/.env.proxy -f deploy/compose.proxy.yaml exec tailscale tailscale ip -4
sudo docker compose --env-file deploy/.env.proxy -f deploy/compose.proxy.yaml exec tailscale tailscale status --json
```

`deploy/.env.proxy` の QSV_TAILNET_IP を **この新ノードの IPv4** に置き換える。ホスト server-a の IP は使わない。初期値127.0.0.1は安全な初期状態として loopback に限定するもので、このままでは Tailnet から接続できない。

Self.DNSName が `qsv.tailnet-name.ts.net.` であることを確認し、違う場合は QSV_PUBLIC_HOST を実際の値へ変更する（末尾のドットは除去）。同名ノードがあると接尾辞が付く場合がある。QSV_UPSTREAM の既定値は `192.168.0.1:18080`。

### 3. Caddy の検証・起動

```sh
sudo docker compose --env-file deploy/.env.proxy -f deploy/compose.proxy.yaml run --rm --no-deps proxy caddy validate --config /etc/caddy/Caddyfile
sudo docker compose --env-file deploy/.env.proxy -f deploy/compose.proxy.yaml up -d
sudo docker compose --env-file deploy/.env.proxy -f deploy/compose.proxy.yaml logs --tail=50 proxy
```

初期設定のドメインで登録された場合の URL は **https://qsv.tailnet-name.ts.net/**。ポート番号の指定は不要。証明書は専用 tailscaled の socket から取得するため、Tailnet の HTTPS 証明書機能が有効であることが前提。ホストの socket は共有しない。

Caddy は TS_USERSPACE=false の Tailscale とネットワークを共有し、新ノードの IPv4:443 のみを listen する。HTTP リダイレクト用80番と管理APIは無効。ホストのポートマッピングや Funnel は使わない。Tailscale は /dev/net/tun と NET_ADMIN、Caddy は低ポート用 NET_BIND_SERVICE を使用する。QNAP アプリの権限は変更しない。

### 4. 既存 grants とバックエンド IP 制限

提示された既存ポリシーでは、tag:www-server の TCP 443 は **group:admins と tag:client** の両方から許可される。この範囲でよければ grants・tagOwners の追加変更は不要。管理者だけに絞る場合には専用タグと grant が必要だが、現在の構成では追加しない。ホストの8443を許可するルールは不要。

QNAP から見た LAN 接続元は通常 Docker の NAT 後の server-a の LAN IP（観測環境は192.168.0.2）になる。Tailnet の新ノード IP を QSV_ALLOWED_PROXY_IPS に指定しない。経路変更や NAT の有無は実測する。403 の場合は proxy コンテナの環境から upstream への通信を確認し、QNAP の allowlist が実際の LAN 送信元を許可しているか確認する。

既存プロキシを起動済みの場合、`up -d` で proxy は新しいネットワークへ再作成される。旧ホスト8443リスナーが消えたことを確認する。Compose の名前 qsv-proxy は引き継ぐが、ホスト Tailscale や他サービスには影響しない。

### 運用

- 設定変更後は同じ `--env-file` と `-f` を付けた `up -d` で再作成する。
- Tailscale を再作成した場合は、ネットワーク名前空間を共有する Caddy も `up -d --force-recreate proxy` で再作成する。
- 停止は同じオプションの `down`。**`down -v` は state と証明書を消すので使用しない**。state を削除すると新しいノードとして再登録される。
- 最終確認は別の許可済み Tailnet 端末のブラウザで行い、LAN IP の443/8443からアクセスできないことも確認する。

Docker 起動は sudo の対話認証が必要なため、この環境からは未実施。Compose / Caddy の構成検証と実際のノード登録・ブラウザ到達性は区別する。
