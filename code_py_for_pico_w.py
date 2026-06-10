# CircuitPython用の送信例
import os
import time
import wifi
import socketpool
import ssl
import adafruit_requests

SSID = os.getenv('CIRCUITPY_WIFI_SSID')
PASSWORD = os.getenv('CIRCUITPY_WIFI_PASSWORD')
POST_URL = 'https://あなたのアプリ名.onrender.com/api'
DEVICE_NAME = 'otsu_01'
LAT = 35.0116
LNG = 135.7681


def connect_wifi():
    if not wifi.radio.connected:
        print('Connecting Wi-Fi...')
        wifi.radio.connect(SSID, PASSWORD)
        print('Wi-Fi OK:', wifi.radio.ipv4_address)


def make_session():
    pool = socketpool.SocketPool(wifi.radio)
    context = ssl.create_default_context()
    return adafruit_requests.Session(pool, context)


connect_wifi()
requests = make_session()

# 本番ではBME280の実測値に置き換える
payload = {
    'name': DEVICE_NAME,
    'temp': 24.2,
    'hum': 58.1,
    'press': 1007.9,
    'lat': LAT,
    'lng': LNG,
}

r = requests.post(POST_URL, json=payload)
print('status =', r.status_code)
print('response =', r.text)
r.close()

while True:
    time.sleep(10)
