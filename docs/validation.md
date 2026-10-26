# 開発環境での検証

人工 crontab を使い、Python 3.14.4 / FastAPI 0.162.0 / croniter 6.2.4 で pytest 10件成功。API の TestClient は、開発環境のサンドボックス内でスレッド間通知が停止したため、制限外で実行した。Starlette TestClient から httpx 連携の将来的な非推奨警告が1件出るがテストは成功。

検証内容：コメント・環境変数・不正記法、安定 ID、秘密情報の非表示、件数・サイズ上限、月日/曜日 OR、存在しない日付、DST ギャップと繰り返し、次回予定、7日分の API、CSV 数式対策、フィルタ、異なる Origin の拒否、Collector 例外の隔離、読み取り失敗時の古いキャッシュ表示。

旧構成を前提に `docker compose config --quiet` と nas-a-admin + 接続 override の Compose 構文・マージを確認済み。ただし、これは同一 Docker ホストを想定した検証であり、QNAP → LAN → server-a という新構成の成立を示さない。旧設定例は新構成には使用しない。既存サービスの変更・起動は行っていない。

2026-10-26 に新構成へドキュメントを訂正した後、プロキシ IP allowlist と LAN HTTP 公開を実装した。現在の全テストは **34件成功**（Python 3.14.4）。個別 IPv4/IPv6、IPv4-mapped IPv6、空の全拒否、不正な設定の起動拒否、全ルートの制限、転送ヘッダー偽装の無効化、loopback の healthz 例外、許可されたプロキシの中継を検証した。Starlette の非推奨警告1件は継続している。

新 Compose はサンプルの bind IP・プロキシ IP を指定して構文を確認。実際の IP が空のままなら Compose が設定エラーとなる。

実際の Uvicorn を開発環境の loopback で起動し、送信元を別の loopback IP に変えた TCP 接続でも検証した。許可 peer は200、非許可 peer は403、許可 IP の転送ヘッダー偽装は403、許可 peer の転送ヘッダーが非許可 IP でも200となること、healthz 以外には loopback の例外がないことを確認済み。旧同一ホスト用 override は無効化し、Caddy 例の upstream は QNAP の LAN HTTP に変更した。

未検証：Docker イメージのビルド・コンテナ起動（開発 PC の Docker daemon に接続権限なし）、Python 3.13 のコンテナ内実行、実ブラウザの描画と操作、QNAP の実設定・権限、server-a から QNAP への到達性と実際の送信元、他の LAN 端末への HTTP 403、Tailnet 内外からの到達性、server-a のプロキシ設定の実機適用、両ホストの再起動後の復旧。これらを済ませるまで初期バージョンの受け入れ完了とはしない。
