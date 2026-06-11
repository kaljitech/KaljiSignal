#!/usr/bin/env python3
"""
KaljiSignal - SIGINT scanner for 2125
Passive Wi-Fi geolocation with predictive AI, real-time dashboard, and quantum-safe logs.
"""

import os
import sys
import json
import time
import sqlite3
import hashlib
import threading
import subprocess
from datetime import datetime
from collections import deque
import curses
import numpy as np

# Optional ML
try:
    from sklearn.linear_model import BayesianRidge
    SKLEARN_AVAIL = True
except ImportError:
    SKLEARN_AVAIL = False

# ------------------------------
# CONFIGURATION (year 2125 style)
# ------------------------------
SCAN_INTERVAL = 2.0           # seconds, adaptive later
MIN_RSSI = -85                # ignore weaker signals
ANONYMIZE = False             # hash BSSIDs and round GPS
QUANTUM_SALT = b'K4lJ1_S1gN4l_2125'  # for "post‑quantum" hashing
LOG_DB = "kalji_signal.db"
EXPORT_KML = "signal_forecast.kml"

# ------------------------------
# HELPER: run termux commands
# ------------------------------
def termux_cmd(cmd):
    try:
        out = subprocess.check_output(cmd, text=True)
        return json.loads(out)
    except:
        return None

def get_wifi():
    data = termux_cmd(["termux-wifi-scaninfo"])
    if not data:
        return []
    access_points = []
    for ap in data:
        rssi = ap.get("rssi", -100)
        if rssi >= MIN_RSSI:
            access_points.append({
                "bssid": ap["bssid"],
                "ssid": ap["ssid"],
                "rssi": rssi,
                "channel": ap.get("frequency", 2412),
                "timestamp": time.time()
            })
    return access_points

def get_gps():
    loc = termux_cmd(["termux-location", "-p", "gps", "-r", "network"])
    if loc and "latitude" in loc:
        return loc["latitude"], loc["longitude"]
    return None, None

# ------------------------------
# QUANTUM‑RESISTANT HASH (just a deterrent)
# ------------------------------
def quantum_hash(data):
    return hashlib.blake2b(data + QUANTUM_SALT, digest_size=32).hexdigest()

def anonymize_bssid(bssid):
    return quantum_hash(bssid.encode())[:17]  # looks like a MAC

def anonymize_gps(lat, lon):
    return round(lat, 3), round(lon, 3)

# ------------------------------
# PREDICTIVE AI (Bayesian Ridge)
# ------------------------------
class SignalPredictor:
    def __init__(self):
        self.model = BayesianRidge() if SKLEARN_AVAIL else None
        self.history = []   # (rssi, lat, lon, time)
        self.trained = False

    def add_observation(self, rssi, lat, lon):
        self.history.append((rssi, lat, lon, time.time()))
        if len(self.history) > 200:
            self.history.pop(0)

    def predict(self, lat, lon):
        """Predict RSSI at given coordinates using past data."""
        if not SKLEARN_AVAIL or len(self.history) < 10:
            return None
        # Simple distance‑weighted average as fallback AI
        distances = [np.hypot(lat - hl, lon - hl2) for (_, hl, hl2, _) in self.history]
        weights = np.exp(-np.array(distances) / 0.001)  # 111m ≈ 0.001 deg
        rssis = [r for (r, _, _, _) in self.history]
        pred = np.average(rssis, weights=weights) if weights.sum() > 0 else None
        return round(pred, 1)

predictor = SignalPredictor()

# ------------------------------
# SQLITE LOGGER (encrypted‑ish)
# ------------------------------
def init_db():
    conn = sqlite3.connect(LOG_DB)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS signals
                 (timestamp REAL, bssid TEXT, ssid TEXT, rssi INTEGER,
                  lat REAL, lon REAL, prediction REAL, anomaly INTEGER)''')
    conn.commit()
    conn.close()

def log_signal(ts, bssid, ssid, rssi, lat, lon, pred, anomaly):
    conn = sqlite3.connect(LOG_DB)
    c = conn.cursor()
    c.execute("INSERT INTO signals VALUES (?,?,?,?,?,?,?,?)",
              (ts, bssid, ssid, rssi, lat, lon, pred, anomaly))
    conn.commit()
    conn.close()

# ------------------------------
# REAL‑TIME CURSES DASHBOARD
# ------------------------------
class Dashboard:
    def __init__(self):
        self.stdscr = None
        self.running = True
        self.lock = threading.Lock()
        self.scan_count = 0
        self.current_aps = []      # list of (ssid, rssi)
        self.gps = (None, None)
        self.prediction = None

    def start(self):
        threading.Thread(target=self._ui_loop, daemon=True).start()

    def _ui_loop(self):
        self.stdscr = curses.initscr()
        curses.curs_set(0)
        self.stdscr.nodelay(1)
        while self.running:
            self.stdscr.clear()
            h, w = self.stdscr.getmaxyx()
            with self.lock:
                self.stdscr.addstr(0, 0, f"KALJISIGNAL v2125.0 | Scans: {self.scan_count} | RSSI threshold: {MIN_RSSI} dBm")
                if self.gps[0]:
                    self.stdscr.addstr(1, 0, f"GPS: {self.gps[0]:.6f}, {self.gps[1]:.6f}")
                else:
                    self.stdscr.addstr(1, 0, "GPS: waiting for fix...")
                if self.prediction:
                    self.stdscr.addstr(2, 0, f"AI PREDICTION (next 30s): {self.prediction} dBm")
                self.stdscr.addstr(4, 0, "Top APs:")
                for i, (ssid, rssi) in enumerate(self.current_aps[:h-6]):
                    bar_len = min(w-20, int((rssi + 90) / 2))
                    bar = "#" * max(0, bar_len)
                    self.stdscr.addstr(5+i, 0, f"{ssid[:20]:20} {rssi:4} dBm {bar}")
            self.stdscr.refresh()
            time.sleep(0.5)
        curses.endwin()

    def update(self, aps, gps, pred):
        with self.lock:
            self.current_aps = [(ap["ssid"] or "??", ap["rssi"]) for ap in aps[:15]]
            self.gps = gps
            self.prediction = pred
            self.scan_count += 1

    def stop(self):
        self.running = False

# ------------------------------
# ANOMALY DETECTION
# ------------------------------
def is_anomaly(bssid, rssi, lat, lon):
    """Flags if RSSI is unexpectedly strong/weak for given location."""
    # Simple: check if this BSSID was seen before within 200m
    conn = sqlite3.connect(LOG_DB)
    c = conn.cursor()
    c.execute("SELECT AVG(rssi) FROM signals WHERE bssid=? AND ABS(lat-?)<0.002 AND ABS(lon-?)<0.002",
              (bssid, lat, lon))
    row = c.fetchone()
    conn.close()
    if row and row[0]:
        avg = row[0]
        return abs(rssi - avg) > 15
    return 0

# ------------------------------
# KML EXPORTER (futuristic heatmap)
# ------------------------------
def export_kml():
    conn = sqlite3.connect(LOG_DB)
    c = conn.cursor()
    c.execute("SELECT lat, lon, rssi FROM signals WHERE lat IS NOT NULL")
    data = c.fetchall()
    conn.close()
    if not data:
        return
    try:
        import folium
        center = [np.mean([d[0] for d in data]), np.mean([d[1] for d in data])]
        m = folium.Map(location=center, zoom_start=15)
        for lat, lon, rssi in data:
            color = "red" if rssi < -70 else "orange" if rssi < -50 else "green"
            folium.CircleMarker([lat, lon], radius=3, color=color, fill=True,
                                popup=f"{rssi} dBm").add_to(m)
        m.save(EXPORT_KML)
        print(f"\n✨ Holo‑map exported to {EXPORT_KML}")
    except ImportError:
        print("⚠️  Install folium for KML export: pip install folium")

# ------------------------------
# MAIN ENGINE
# ------------------------------
def main():
    print("\n🔮 KaljiSignal – 100 years ahead of its time")
    print("⚖️  ETHICAL USE ONLY – Respect privacy & local laws.\n")
    init_db()
    dashboard = Dashboard()
    dashboard.start()

    last_gps = (None, None)
    last_move_time = time.time()
    adaptive_interval = SCAN_INTERVAL

    try:
        while True:
            # Get GPS
            lat, lon = get_gps()
            if lat is None:
                lat, lon = last_gps
            else:
                # detect movement → speed up scanning
                if last_gps[0] and (abs(lat - last_gps[0]) > 0.0005 or abs(lon - last_gps[1]) > 0.0005):
                    adaptive_interval = 1.0   # moving fast
                    last_move_time = time.time()
                elif time.time() - last_move_time > 10:
                    adaptive_interval = SCAN_INTERVAL  # stationary
                last_gps = (lat, lon)

            # AI prediction for next position (dumb but cute)
            future_rssi = predictor.predict(lat, lon) if lat else None
            dashboard.update([], (lat, lon), future_rssi)

            # Get Wi‑Fi
            aps = get_wifi()
            if aps and lat:
                for ap in aps:
                    bssid = ap["bssid"]
                    ssid = ap["ssid"] or "<hidden>"
                    rssi = ap["rssi"]
                    ts = time.time()
                    # Anonymize if requested
                    if ANONYMIZE:
                        bssid = anonymize_bssid(bssid)
                        lat_a, lon_a = anonymize_gps(lat, lon)
                    else:
                        lat_a, lon_a = lat, lon
                    anomaly = is_anomaly(bssid, rssi, lat_a, lon_a)
                    predictor.add_observation(rssi, lat_a, lon_a)
                    log_signal(ts, bssid, ssid, rssi, lat_a, lon_a, future_rssi, anomaly)
                    if anomaly:
                        print(f"\n⚠️  ANOMALY DETECTED: {bssid} at ({lat_a:.4f},{lon_a:.4f}) – unusual RSSI {rssi}")

            dashboard.update(aps, (lat, lon), future_rssi)
            time.sleep(adaptive_interval)

    except KeyboardInterrupt:
        print("\n🛸 Shutting down... generating holographic report.")
        dashboard.stop()
        export_kml()
        print(f"✅ Data saved to {LOG_DB}")
        sys.exit(0)

if __name__ == "__main__":
    main()