【5人用 Picoセンサーデータベース 完成版】

1. GitHubにこのフォルダをそのままアップ
2. Renderで New Web Service
3. GitHubリポジトリを選択
4. buildCommand: pip install -r requirements.txt
5. startCommand: gunicorn server:app
6. デプロイ完了後、以下で確認
   - https://あなたのアプリ名.onrender.com/
   - https://あなたのアプリ名.onrender.com/api/latest

【送信先】
POST /api

JSON例
{
  "name": "otsu_01",
  "temp": 23.8,
  "hum": 56.4,
  "press": 1008.2,
  "lat": 35.0116,
  "lng": 135.7681
}

【機能】
- sensor_history: 全履歴保存
- sensor_latest: 同じ名前は最新だけ保持
- 地図表示
- 最新一覧表示
- 履歴APIあり

【補足】
- SQLiteは5人規模なら十分
- Render無料版はスリープあり
- SQLiteは無料運用で永続性に弱い場合があるため、講座や試作向け
