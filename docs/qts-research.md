# QTS 調査状況

## 配置と取得方式

QSV は QNAP 上のコンテナで収集・API・Web UI を動かす。QNAP では Tailscale を使わない。server-a 上の QSV 専用 Tailscale コンテナと Caddy が、専用ノード名の443で受けて QNAP へ LAN HTTP で転送する。入口は既存 tag:www-server の grants、バックエンドは実接続元 IP allowlist で制限する。

公開構成の参考は `/mnt/iscsi/containers/nas-a-admin` の README、Compose、Caddyfile。Tailscale コンテナとネットワーク・socket を共有する Caddy、Tailscale からの証明書取得、LAN upstream への中継を参照した。参照ファイルの内容と実際の稼働状態は区別する。秘密値や Tailscale state の内容は調査対象にしない。

## 収集対象

| 収集対象 | 取得方式 | 権限 | 対応可否 | 注意事項 |
|---|---|---|---|---|
| cron | /etc/config/crontab の読み取り | 実機の所有者・モードは未確認 | 標準5フィールドを実装。利用者が API 応答を確認 | QTS 全設定との照合は未実施。単一ファイルの read-only mount |
| 電源 | QTS 管理画面の `/cgi-bin/sys/sysRequest.cgi` の XML 応答で確認 | 一般ユーザーではコントロールパネルが表示されない。API の最小権限は未確認 | Collector 未実装 | 一部コードを実機で照合済み。ローカルの保存場所は調査中 |
| 再起動（cron） | `/etc/config/crontab` | 既存の cron 読み取りと共通 | 単独の `reboot`、`/etc/init.d/reboot`、`/sbin/reboot`、`/usr/sbin/reboot` を電源に分類 | 実機の土曜 00:00 の行は `0 0 * * 6 /etc/init.d/reboot` |
| RAID | 未確認 | 未確認 | 未対応 | cronコマンド名だけで同定しない |
| SMART | 未確認 | 未確認 | 未対応 | 同上 |
| Snapshot | 未確認 | 未確認 | 未対応 | 内部DBの形式を推測しない |
| HBS 3 | 未確認 | 未確認 | 未対応 | 資格情報を含むDB全体を共有しない |
| セキュリティ・更新・QPKG | 未確認 | 未確認 | 未対応 | インストール有無も未判定 |

crontab のパスは仕様書由来。samples/crontab は人工データで、実機観測の証拠ではない。電源の調査で確認した機種と QTS バージョンを下に記録する。Container Station / QPKG のバージョンは未確認。

## 電源スケジュールの観測

TS-664（x86、Jasper Lake）、QTS 5.2.11 build 3661（2026-10-23）。`/etc/config` 直下の名前を `power|rtc|sched|freschclam` で絞ったところ該当なし。管理画面の電源スケジュールを開いた際の XML には、`QDocRoot/func` のうち `name` が `Power Management` の要素に `ownContent/getScheduleboot` が含まれていた。

サンプルでは `ScheduleEnabled=1`、`PostponeScheduleEnabled=1`、`ScheduleCount=2`。各 `Entry` に `ActionNumber`、`ActionType`、`DaySchedule`、`Hour`、`Min`、`Enabled`、`Year`、`Month`、`Day`、`Name` があった。

| ActionNumber | ActionType | DaySchedule | Hour | Min | Enabled | Year / Month / Day | 管理画面の表示 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 2 | 9 | 0 | 0 | 1 | 2025 / 8 / 7 | 再起動、毎土曜日 00:00、有効 |
| 2 | 3 | 11 | 7 | 0 | 1 | 2026 / 11 / 17 | 電源オン、1度、2026/11/17 07:00、有効 |

この実機では `ActionType=2` が再起動、`3` が電源オン。`DaySchedule=9` は毎土曜日で、`Hour` と `Min` を使う。`11` は1度で、日付と時刻を使う。ほかのコードは未確認。画面ではスケジュール全体の有効化とレプリケーション中の延期が選択されており、XML の全体フラグと一致する。

ブラウザが送信したのは `POST /cgi-bin/sys/sysRequest.cgi`。URL のクエリに `subfunc=power_mgmt` と `sid` が含まれる。既存の一般ユーザーでログインすると File Station 6 とヘルプセンターが表示され、コントロールパネルは表示されなかった。API 自体が要求する権限と常駐 Collector 用のセッション取得・更新方法は未確認。[QTS 認証 API](https://download.qnap.com/dev/API_QNAP_QTS_Authentication.pdf)

### ローカルの取得元候補を調べる

QNAP の SSH シェルで実行する。`/etc/config` 直下の `.conf` と `crontab` を対象に、電源スケジュールに関連しそうなキーやコマンドを含むファイルのパスだけを表示する。候補が見つかったら電源スケジュール画面の設定と照合する。

```sh
grep -Eil 'power.?sched|sched(ule)?.?boot|boot.?sched|day.?schedule|postpone.?schedule|action.?number|(^|[[:space:]/])(poweroff|reboot|shutdown)([[:space:]]|$)' \
  /etc/config/*.conf /etc/config/crontab
```

実機では `acpi.conf`、`uLinux.conf`、`crontab` が一致した。ほかに現在のユーザーで読み取れないファイルがあった。まず `acpi.conf` のアクセス権、セクション、キー、数値で構成される値を確認する。

```sh
ls -lnL /etc/config/acpi.conf
awk '
  /^[[:space:]]*\[/ { print; next }
  /^[[:space:]]*[#;]/ { next }
  {
    sep = index($0, "=")
    if (!sep) next
    value = substr($0, sep + 1)
    if (value ~ /^[[:space:]0-9,;:.\/-]+$/) print
    else print substr($0, 1, sep) " <省略>"
  }
' /etc/config/acpi.conf
```

`acpi.conf` では `event` と `action` の組が2つ見つかった。時刻や繰り返しの項目は確認できなかった。残る2ファイルは次のコマンドで照合する。`uLinux.conf` からは電源関連のキーと数値だけを、`crontab` からは電源関連の行の時刻フィールドと一致した語だけを表示する。

```sh
awk '
  /^[[:space:]]*\[/ { section = $0; next }
  /^[[:space:]]*[#;]/ { next }
  {
    sep = index($0, "=")
    if (!sep) next
    key = substr($0, 1, sep - 1)
    if (tolower(section " " key) !~ /power|sched|reboot|shutdown|rtc/) next
    value = substr($0, sep + 1)
    if (value !~ /^[[:space:]0-9,;:.\/-]+$/) value = " <省略>"
    print section, key "=" value
  }
' /etc/config/uLinux.conf

awk '
  $1 ~ /^[0-9*]/ && NF >= 6 {
    for (i = 6; i <= NF; i++) {
      if (match(tolower($i), /poweroff|reboot|shutdown|scheduleboot|rtcwake/)) {
        print $1, $2, $3, $4, $5, substr($i, RSTART, RLENGTH)
        break
      }
    }
  }
' /etc/config/crontab
```

`uLinux.conf` では電源復旧と UPS に関係する設定が見つかった。`crontab` には `0 0 * * 6 /etc/init.d/reboot` があり、画面の再起動予定と一致した。引数なしのこの行をテストデータに使った。1回限りの電源オンに対応するローカルの取得元は未特定。

## 実機で確認する事項

QNAP 上で `uname -m`、`docker version`、`docker compose version` を参照し、QTS と Container Station のバージョンは管理画面で確認する。`ls -l /etc/config/crontab` で必要権限を確認する。crontab の内容を共有する場合はコマンド引数やパスに含まれる秘密値をローカルで除去する。

電源・ストレージ・Snapshot・HBS 3 は、管理画面の設定と保存情報を読み取りで照合する。機密データがあるディレクトリ全体のコピーや再帰探索を初手にしない。公開された参照 API があれば優先し、なければ実際に観測したファイル形式・QTS/QPKG バージョン・匿名化サンプル・権限を記録して Collector を実装する。QTS 内部 API / DB の推測は実装の根拠にしない。

専用ノードの Tailnet Lock 署名・DNS 名・IP、証明書取得、NAT 後の LAN 送信元、QNAP の allowlist の有効性を確認する。稼働確認の範囲は [validation.md](validation.md)、操作手順は [deployment.md](deployment.md) を参照。
