from machine import Pin, I2C
from time import sleep
import network
import ntptime
import time
import urequests
import bme280

# ====== 講座生ごとに書き換え ======
SSID = "あなたのSSID"
PASSWORD = "あなたのWi-Fiパスワード"
URL = "https://temperature-map.onrender.com/api"
NAME = "pico_01"
LAT = 35.0
LNG = 135.8
SEND_INTERVAL_SEC = 30
# ==================================

# 配線例: GP5=SCL, GP4=SDA, BME280 address=0x76
i2c = I2C(0, scl=Pin(5), sda=Pin(4), freq=100000)
sensor = bme280.BME280(i2c=i2c, address=0x76)


def to_float(value):
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value)
    num = ""
    for ch in s:
        if ch.isdigit() or ch in ".-":
            num += ch
    return float(num)


def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        wlan.connect(SSID, PASSWORD)
        timeout = 30
        while not wlan.isconnected() and timeout > 0:
            print("Wi-Fi status:", wlan.status())
            sleep(1)
            timeout -= 1
    if not wlan.isconnected():
        raise RuntimeError("Wi-Fi接続に失敗しました status=" + str(wlan.status()))
    print("Wi-Fi connected:", wlan.ifconfig())
    return wlan


def sync_time():
    try:
        ntptime.settime()
        print("NTP OK:", time.localtime())
    except Exception as e:
        print("NTP失敗、続行:", e)


def send_data(temp, hum, press):
    data = {
        "name": NAME,
        "temp": temp,
        "hum": hum,
        "press": press,
        "lat": LAT,
        "lng": LNG,
    }
    response = None
    try:
        response = urequests.post(URL, json=data)
        print("Status:", response.status_code)
        print("Body:", response.text)
    except Exception as e:
        print("送信エラー:", e)
    finally:
        if response:
            response.close()


connect_wifi()
sync_time()

while True:
    try:
        temp_raw, pressure_raw, humidity_raw = sensor.values
        temp = to_float(temp_raw)
        press = to_float(pressure_raw)
        hum = to_float(humidity_raw)

        print("温度:", temp, "℃")
        print("湿度:", hum, "%")
        print("気圧:", press, "hPa")
        send_data(temp, hum, press)
        print("----------------------")
    except Exception as e:
        print("メイン処理エラー:", e)
        try:
            connect_wifi()
        except Exception as e2:
            print("再接続失敗:", e2)

    sleep(SEND_INTERVAL_SEC)
