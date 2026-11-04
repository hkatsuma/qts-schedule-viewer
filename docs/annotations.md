# タグ・表示名の保存と API

タグと表示名は QSV の注釈であり、NAS のジョブ・設定を変更しない。注釈の対象は `definition_id` で、同じ定義の重複行に共通で反映する。ジョブ識別と変更時の扱いは [job-identity.md](job-identity.md) に従う。

## 保存内容と実行条件

`QSV_DB_PATH`（既定 `/data/qsv.sqlite3`）に SQLite DB を置く。QNAP のローカル Docker named volume `qsv-data` を `/data` に割り当てる。開発 PC がマウントした NAS 共有や SMB/NFS 上に DB を置かない。コンテナの root filesystem は読み取り専用のままで、書き込み先はこのボリュームに限定する。

DB に保持するのは定義 ID、表示名、タグ名・関連付け、更新版、最終確認時刻と有無の状態だけ。コマンド、環境変数、cron 式、予定一覧は保存しない。収集結果はメモリ管理を継続し、通常 API・CSV にコマンド原文を含めない。明示的に入力された表示名・タグの文字列は保存・表示・CSV 出力される。

初期スキーマは `PRAGMA user_version=1`。トランザクション内で初期化し、未知のスキーマは起動エラーにする。DB の初期化失敗・書き込み不可では起動を失敗させ、メモリだけの注釈保存に切り替えない。稼働中に DB を利用できない場合は API が503を返す。DB観測の更新失敗時は次の定期・手動収集で再試行する。

SQLite は WAL、接続ごとに foreign_keys を有効化し、書き込みは `BEGIN IMMEDIATE` と5秒のロック待機を使う。注釈を変更する際は呼出元の版を照合し、競合は409で返す。版は単調増加する DB 全体の番号を割り当てる。収集による最終確認時刻の更新では注釈の版を変更しない。

## タグと表示名の規則

- タグは最大200件、1件の名前は NFC 正規化・前後空白除去後で1〜40文字。大小文字を casefold した名前は重複不可。制御・不可視制御文字は受け付けない。
- 1定義に付けられるタグは最大64件。未登録 ID と重複 ID を拒否する。
- 表示名は NFC 正規化・前後空白除去後で最大120文字。空は取得元の名前に戻す。表示名とタグ名は HTML ではなく文字列として描画する。
- タグ名を変更してもタグ ID と関連付けは維持する。削除は不在定義も含むすべての関連付けを外す。削除の影響を受ける注釈の版も変更し、古い編集内容による復活を防ぐ。
- 注釈の削除は表示名とタグ関連付けを空にする。グローバルなタグ自体は残す。

## API

全ルートにプロキシ IP 制限を適用する。書き込みは JSON のみで16KiBまで。異なる Origin、不正な Origin、cross-site の Sec-Fetch-Site を拒否する。HTTPS 終端はリバースプロキシのため、Origin の http/https を認め Host の一致を確認する。Origin がない CLI は許可 IP から利用できる。独自ユーザー認証やロール分離は行わず、Tailnet ACL で許可された閲覧者は QSV の注釈も編集できる。

| 操作 | メソッドとパス | 本文 |
| --- | --- | --- |
| タグ一覧 | GET `/api/tags` | なし |
| タグ作成 | POST `/api/tags` | `name` |
| タグ名変更 | PUT `/api/tags/{id}` | `name`, `version` |
| タグ削除 | DELETE `/api/tags/{id}` | `version` |
| 保存定義と注釈の一覧 | GET `/api/annotations` | なし |
| 注釈保存 | PUT `/api/annotations/{definition_id}` | `version`, `display_name`, `tag_ids` |
| 注釈削除 | DELETE `/api/annotations/{definition_id}` | `version` |
| 明示コピー | POST `/api/annotations/copy` | `source_id`, `target_id`, `source_version`, `target_version`, `overwrite`（既定 false） |

注釈一覧には未編集の定義も含め、`presence` は `present` / `absent` / `unknown`、`last_seen_at` は実際に取得できた最終時刻を返す。表示名・タグを持つ定義は画面の管理対象として表示する。

注釈保存とコピー先は、直近の収集で取得できた定義に限定する。取得失敗時の古いキャッシュだけでは書き込まない。注釈削除は不在・未確認の定義にも行える。コピーは双方の版を照合し、移行先に既存注釈があれば `overwrite=true` を明示しなければ409。移行元は変更しない。収集と注釈更新は同じサービスのロック下で行い、更新時に移行先の存在を再検証する。

完全取得（ok / empty）だけが不在を確定する。partial では今回取得した定義を present、それ以外を unknown にする。収集失敗や古いキャッシュでは全定義を unknown にし、保存済み注釈を消さない。完全に同じ定義が再登場すれば同じ保存注釈を使う。

## 表示と絞り込み

一覧・週間・月間・CSV には表示名を反映する。Task.name は表示名があればその値、なければ取得名。`original_name` は取得名、`display_name` は利用者が保存した値。`tags` はタグ情報、`annotation_version` は編集時の版。Collector のメモリ上のタスクは書き換えない。

各表示 API は繰り返し指定する `tag=ID` と `tag_match=any|all` を受け付ける。any（OR）が既定、all は全選択タグの付いた定義だけを返す。タグ未選択は制限なし、存在しない選択 ID は一致なしとして扱う。検索・実行頻度等の条件と組み合わせられ、週間の予定展開前にも適用する。CSV は適用後の表示名・タグと取得名を含み、数式開始文字をエスケープする。

## バックアップ・復元・削除

オンラインバックアップは Python の SQLite backup API を使う。DB 本体だけを稼働中に cp しない。バックアップは既存ファイルを上書きせず、単一ファイルとして保存する。

QNAP の main のリポジトリルートで、バックアップ名を設定して実行する。

```sh
QSV_BACKUP="qsv-backup-$(date +%Y%m%d-%H%M%S).sqlite3"
sudo docker compose exec -T qsv python -m src.manage_db backup "/data/$QSV_BACKUP"
sudo docker compose cp "qsv:/data/$QSV_BACKUP" "./$QSV_BACKUP"
```

ホストへコピーしたバックアップは別の保管先にも保存する。`/data` 内だけではボリューム消失への備えにならない。バックアップは Git 管理しない。複数 NAS で DB を共用しない。

復元は qsv を停止し、同じ版のイメージを使って行う。ボリューム内にバックアップがある場合：

```sh
sudo docker compose stop qsv
sudo docker compose run --rm --no-deps --entrypoint python qsv \
  -m src.manage_db restore "/data/$QSV_BACKUP" --offline
sudo docker compose up -d --no-build qsv
```

ホストにしかバックアップがない場合は、停止前に `sudo docker compose cp "./$QSV_BACKUP" "qsv:/data/$QSV_BACKUP"` で戻す。コピー後、非 root のアプリから読み取れる所有者・権限にする。コピーを省くなら、復元用の一時コンテナへバックアップを read-only bind mount して復元元に指定してもよい。

復元コマンドはバックアップのスキーマと整合性を検証し、停止した旧 DB を checkpoint してから、一時ファイル経由で置き換える。`--offline` は停止を利用者が確認した指定であり、稼働プロセスを自動停止する機能ではない。失敗時にはアプリを再起動する前に原因を解消する。

更新前にはバックアップを取得する。将来のスキーマ更新時は対応する移行を実装し、ダウングレードは対応版イメージと対応版バックアップをセットで復元する。`docker compose down` ではデータは残る。`down -v` や Docker volume の削除は全注釈を削除するため、破棄するときだけ明示して行う。
