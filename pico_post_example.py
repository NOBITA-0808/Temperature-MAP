# PCのPythonでも試せます
import requests

url = 'https://あなたのアプリ名.onrender.com/api'

data = {
    'name': 'otsu_01',
    'temp': 23.8,
    'hum': 56.4,
    'press': 1008.2,
    'lat': 35.0116,
    'lng': 135.7681,
}

r = requests.post(url, json=data, timeout=15)
print(r.status_code)
print(r.text)
