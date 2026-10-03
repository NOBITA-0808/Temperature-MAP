【Pico W + MicroPython + Render + SQLite センサーマップ】

■ できること
- Pico Wから温度・湿度・気圧をPOST受信
- press と pres の両方に対応
- SQLiteに全履歴を保存
- 地図上に温度ラベルを常時表示
- 一覧行またはマーカーをクリックして地点別グラフを切替
- 全地点の気温を同じ比較グラフに表示
- pico_test1 → 自宅付近、pico_test2 → 大津駅北口
- CSVダウンロード
- スマートフォン表示

■ Render設定
Build Command:
  pip install -r requirements.txt

Start Command:
  gunicorn --bind 0.0.0.0:$PORT --workers 1 server:app

■ 主なURL
地図:
  https://あなたのアプリ名.onrender.com/

POST送信先:
  https://あなたのアプリ名.onrender.com/api

最新データ:
  https://あなたのアプリ名.onrender.com/latest
  https://あなたのアプリ名.onrender.com/api/latest

履歴:
  https://あなたのアプリ名.onrender.com/history?name=pico_test1&hours=24

比較:
  https://あなたのアプリ名.onrender.com/compare?hours=24

CSVダウンロード:
  https://あなたのアプリ名.onrender.com/csv

■ Pico側
micropython_pico_w_render.py を Pico W 側の main.py として使えます。
SSID、PASSWORD、NAME、LAT、LNG を講座生ごとに変更してください。

■ 注意
Render無料版では SQLite ファイルは再デプロイ等で消える可能性があります。
/var/data にディスクがある場合は、そこへ自動保存します。
