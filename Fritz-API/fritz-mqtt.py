import datetime
import json
import os
import time
import xml.etree.ElementTree as ET
import paho.mqtt.client as mqtt
import requests

# 1. Parse configuration safely using Home Assistant's standard options file
OPTIONS_PATH = "/data/options.json"

if not os.path.exists(OPTIONS_PATH):
    print(f"Error: Configuration file not found at {OPTIONS_PATH}. Is this running as a HA Add-on?")
    exit(1)

with open(OPTIONS_PATH, "r") as f:
    options = json.load(f)

FRITZ_IP = options.get("repeater_ip")
MQTT_IP = options.get("mqtt_ip")
MQTT_USER = options.get("mqtt_user")
MQTT_PASSWORD = options.get("mqtt_password")

TARGET_MACS = options.get("device_mac_list", [])
TOPICS = options.get("device_name_list", [])

if len(TOPICS) != len(TARGET_MACS):
    print("Configuration Error: 'device_name_list' and 'device_mac_list' must have the exact same number of items.")
    exit(1)

# 2. Setup MQTT Client
client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
if MQTT_USER and MQTT_PASSWORD:
    client.username_pw_set(MQTT_USER, MQTT_PASSWORD)
client.reconnect_delay_set(min_delay=1, max_delay=30)

def send_state(state, topic):
    try:
        client.publish(topic, state, qos=1, retain=True)
    except Exception as e:
        print(f"MQTT publish error: {e}")

session = requests.Session()

def is_device_active(mac, ip_address):
    url = f"http://{ip_address}:49000/upnp/control/hosts"
    headers = {
        "Content-Type": 'text/xml; charset="utf-8"',
        "SOAPACTION": '"urn:dslforum-org:service:Hosts:1#GetSpecificHostEntry"',
        "User-Agent": "AVM UPnP/1.0 Client 1.0"
    }
    data = f"""<?xml version="1.0" encoding="utf-8"?>
    <s:Envelope s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/" xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" >
    <s:Header><h:InitChallenge xmlns:h="http://soap-authentication.org/digest/2001/10/" s:mustUnderstand="1"></h:InitChallenge ></s:Header>
    <s:Body>
        <u:GetSpecificHostEntry xmlns:u="urn:dslforum-org:service:Hosts:1">
            <NewMACAddress>{mac}</NewMACAddress>
        </u:GetSpecificHostEntry>
    </s:Body>
    </s:Envelope>"""
    try:
        response = session.post(url, headers=headers, data=data, timeout=5)
        response.raise_for_status()
        root = ET.fromstring(response.text)
        active_el = root.find(".//NewActive")
        return active_el is not None and active_el.text == "1"
    except Exception as e:
        raise RuntimeError(f"Fritzbox API error: {e}")

# Connect to MQTT
try:
    print(f"Connecting to MQTT Broker: {MQTT_IP}...")
    client.connect(MQTT_IP, 1883, 60)
except Exception as e:
    print(f"MQTT Connection failed: {e}. Will retry automatically.")

client.loop_start()

# Build device structural state tracking
devices = []
for name, mac in zip(TOPICS, TARGET_MACS):
    devices.append({
        "name": name,
        "mac": mac,
        "is_home": False,
        "fail_count": 0,
        "mqtt_topic": f"fritzapi_connection/{name}"
    })

print("Fritzbox MQTT Monitor Add-on Started.")

consecutive_errors = 0

# Loop
while True:
    try:
        for device in devices:
            active = is_device_active(device["mac"], FRITZ_IP)
            timestamp = datetime.datetime.now().strftime("%H:%M:%S")

            if active:
                device["fail_count"] = 0
                send_state("home", device["mqtt_topic"])
                if not device["is_home"]:
                    print(f"[{timestamp}] {device['name']} marked as HOME")
                    device["is_home"] = True
            else:
                if device["fail_count"] < 3:
                    device["fail_count"] += 1
                
                if device["fail_count"] == 3:
                    send_state("not_home", device["mqtt_topic"])
                    if device["is_home"]:
                        print(f"[{timestamp}] {device['name']} marked as NOT_HOME")
                        device["is_home"] = False
                        
        consecutive_errors = 0
        
    except Exception as e:
        consecutive_errors += 1
        if consecutive_errors >= 10:
            print(f"Continuous API failures tracking router. Error: {e}")
            consecutive_errors = 0
            
    time.sleep(30)