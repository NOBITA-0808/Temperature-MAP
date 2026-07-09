【Pico W + MicroPython + Render + SQLite センサーマップ Ver.1.0】

■ できること
- Pico Wから温度・湿度・気圧をPOST受信
- SQLiteに全履歴を保存
- sensor_latestに端末ごとの最新値を保存
- 地図上に温度ラベルを常時表示
- 端末ごとの過去24時間グラフ表示
- CSVダウンロード

■ Render設定
Build Command:
  pip install -r requirements.txt

Start Command:
  gunicorn server:app

■ 主なURL
地図:
  https://あなたのアプリ名.onrender.com/

POST送信先:
  https://あなたのアプリ名.onrender.com/api

最新データ:
  https://あなたのアプリ名.onrender.com/api/latest

履歴:
  https://あなたのアプリ名.onrender.com/api/history

端末指定・24時間:
  https://あなたのアプリ名.onrender.com/api/history?name=pico_01&hours=24

CSVダウンロード:
  https://あなたのアプリ名.onrender.com/download.csv

■ SQLiteテーブル
sensor_history:
  全履歴。送信のたびに1行追加。

sensor_latest:
  地図表示用。端末名ごとに最新1件だけ保持。

■ Pico側
micropython_pico_w_render.py をPico W側の main.py として使えます。
SSID、PASSWORD、NAME、LAT、LNGを講座生ごとに変更してください。

■ 注意
Render無料版ではSQLiteファイルは再デプロイ等で消える可能性があります。
講座・試作用としては十分ですが、長期保存には外部DBや有料ディスクを検討してください。
