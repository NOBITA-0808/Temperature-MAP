import requests

url = "https://temperature-map.onrender.com/api"

data = {
    "name": "otsu_01",
    "temp": 25.3,
    "hum": 60.2,
    "press": 1008.5,
    "lat": 35.017,
    "lng": 135.854
}

r = requests.post(url, json=data)

print(r.text)