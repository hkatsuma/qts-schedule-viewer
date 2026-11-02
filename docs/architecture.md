# 構成

実行場所は QNAP QTS 上の Docker / Container Station。別 PC への共有マウントは開発用であり、ホストパスは QNAP 側で解決される。

```text
Tailnet のブラウザ
    │ HTTPS（Tailnet のアクセス制御）
    ▼
server-a
    ├── QSV 専用 Tailscale コンテナ（tag:www-server）
    └── 同じネットワークの Caddy / 専用ホスト名の HTTPS 443
             │ LAN（接続元を制限したバックエンド通信）
             ▼
QNAP QTS Host（Tailscale なし）
    └── QSV コンテナ：Collector / キャッシュ / API / Web UI
             ↑ 読み取り専用 bind mount
        /etc/config/crontab 等の確認済み設定
```

ホスト自身の Tailscale とは別に、QSV 専用ノードをコンテナで登録する。ホストポートは公開せず、専用ノード IP の443だけで Caddy が受ける。

収集から画面配信までの単一アプリは QNAP 上に置き、server-a は HTTP の中継だけを担当する。収集結果の別ホストへの同期や、収集用 API の追加は不要。生の QTS 設定ファイルを server-a に共有しない。

Docker bridge network はホストごとに独立しており、両ホストに同名のネットワークを作っても接続できない。プロキシの upstream は、QNAP の到達可能な LAN IP と専用ポートにする。QNAP で LAN IP に限定したポートマッピングを用意し、アプリの接続元 IP allowlist で、許可したプロキシからの要求だけを処理する。実際に見える送信元は、プロキシのコンテナ化や NAT を含め実測する。

採用方針は、信頼するホーム LAN 上の HTTP とプロキシ IP 制限のみ。追加の認証情報は使わない。Tailnet からプロキシへのアクセスは Tailscale ACL が担当し、独自 allowlist は設けない。LAN 区間は Tailscale で暗号化されないことを前提としている。

server-a が停止すると Tailnet から閲覧できなくなるが、QNAP の収集は継続できる。QNAP または LAN 接続の停止時はプロキシが接続失敗を返す。両ホストそれぞれで再起動後の復旧を確認する。

QNAP 用の compose.yaml.example と server-a 用の deploy/proxy/compose.yaml.example を配布する。各ディレクトリで compose.yaml にコピーし、Git 管理外の .env に実環境の値を設定する。QNAP は指定 LAN IP でバックエンドを公開し、server-a の Caddy は LAN upstream へ中継する。IP・ポート・証明書等の実機設定は [deployment.md](deployment.md) を参照。


Collector → 共通 Pydantic モデル → メモリキャッシュ → FastAPI → 外部依存のない HTML / CSS / JavaScript。起動時と既定300秒ごと、手動操作で収集する。スケジュールの変更やジョブ実行は行わない。分類が実証できていない cron は system として表示する。

Collector 単位で状態・前回状態・最終正常取得日時を持つ。読み取り失敗時は前回タスクを残し stale を表示する。部分解析時は現在読めた行を表示し、古いタスクと合成しない。キャッシュは再起動で消える。

収集はスレッドに分離し5秒で待機を打ち切る。タイムアウトした読み取り自体は強制終了できないため、その処理が終わるまで新しい収集スレッドを増やさない。ネットワークファイルシステムが永久に停止した場合はコンテナ再起動が必要になる場合がある。設定は最大1MiB、タスクは500件。タイムラインは7日間・最大20,000予定で、打ち切りを画面に表示する。

GET /api/schedules は安全化済みの一覧と収集状態、GET /api/timeline?start=YYYY-MM-DD は7日分の予定、GET /api/month?month=YYYY-MM-DD は指定月の日別タスク集計、GET /api/export.csv は絞り込み適用後の CSV。POST /api/refresh はキャッシュの再収集のみ。HTTP リクエストからファイルパスを変更できない。

cron の月日と曜日の両方が指定されている場合は OR。予定は実行実績ではない。DST の存在しない時刻は除外し、繰り返す時刻は両方を予定候補とする。実際の QTS cron デーモンによる DST 処理は未検証。NAS のタイムゾーンは自動推測せず QSV_TIMEZONE に明示する。OSのタイムゾーン変更後は設定更新と再起動が必要。

## 接続元 IP の判定

`QSV_ALLOWED_PROXY_IPS` に、QNAP が実際の TCP 接続元として認識するプロキシの IP をカンマ区切りで指定する。IPv4 / IPv6 の個別 IP を許可し、CIDR・ホスト名・ワイルドカードは受け付けない。IPv4-mapped IPv6 は IPv4 と同一視する。未設定・空は全拒否、不正な項目は起動エラー。設定変更にはコンテナの再作成が必要。

全画面・API・CSV・静的ファイルを middleware で制限する。唯一の例外はコンテナ内 loopback からの `/healthz`。loopback でもほかの画面・API は通常の制限対象となる。許可されない要求には内容を含めず HTTP 403 を返す。これはアプリ層の拒否であり、TCP 接続自体を遮断するものではない。

Uvicorn の `--no-proxy-headers` を維持し、`X-Forwarded-For` / `Forwarded` / `X-Real-IP` を判定に使わない。Tailnet の各クライアントを QSV の allowlist に登録する必要はない。逆に Docker 等の NAT で多くの送信元が同じアドレスに見える場合、そのアドレスを許可するだけではプロキシだけに制限できないため、経路・ネットワーク側の制限を確認する。

## 頻度フィルタと月間表示

一覧・週間・月間・CSV は frequency=all / nonfrequent / frequent を受け付ける。API の既定値は全件を返す all。UI の初期値は nonfrequent で、実行対象日の通常24時間に24回以上のタスクを除外する。Task.runs_per_active_day は cron の分・時フィールドの組合せ数。月日・曜日の制約は実行日の判定へ適用する。未対応記法などで算出不可のタスクは nonfrequent に残し、frequent には含めない。非表示件数は一覧 API の hidden_by_frequency で返す。

週間は頻度でタスクを除外してから予定を展開し、20,000件で打ち切る場合は警告する。月間は毎分タスクの全イベントを展開せず、各日・各タスクの最初の時刻と回数を返す。月日と曜日は cron の OR 条件を維持し、存在しない日付に予定を作らない。DST の切り替え日は実在する予定時刻で回数を数えるため、通常日の頻度分類とその日の実行回数が異なる場合がある。

月間は最大31日×収集上限500タスクの日別行に集約する。同じ日のタスクが多い場合は UI で一部を折りたたみ、残りを展開できる。月間表示の日付から週間へ、タスクから詳細へ移動する。頻度フィルタの選択はブラウザの localStorage に保存する。ブラウザにスケジュール自体は永続保存しない。
