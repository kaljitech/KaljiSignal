import json
import subprocess
import time
import csv
import sys

def fetch_telemetry_coordinates():
    try:
        result = subprocess.run(['termux-location', '-p', 'network', '-r', 'once'], 
                                capture_output=True, text=True, timeout=10)
        data = json.loads(result.stdout)
        return {
            "lat": data.get("latitude", 0.0),
            "lon": data.get("longitude", 0.0),
            "accuracy": data.get("accuracy", 0.0)
        }
    except Exception:
        return {"lat": 0.0, "lon": 0.0, "accuracy": 0.0}

def sweep_rf_environment():
    try:
        result = subprocess.run(['termux-wifi-scaninfo'], capture_output=True, text=True, timeout=10)
        return json.loads(result.stdout)
    except Exception as e:
        print(f"[\033[91m-\033[0m] Subsystem Error Intercepting RF Scan: {e}")
        return []

def main():
    log_matrix = "signal_telemetry.csv"
    
    print("\033[92m" + "=== KALJISIGNAL DAEMON v1.0.0 ===" + "\033[0m")
    print(f"[*] Initializing telemetry ingestion loop... Logging to -> {log_matrix}")
    print("[*] Tactical status: ACTIVE. Press CTRL+C to terminate transmission.")
    print("-" * 60)
    
    with open(log_matrix, mode='a', newline='') as raw_file:
        data_logger = csv.writer(raw_file)
        
        if raw_file.tell() == 0:
            data_logger.writerow(["Timestamp", "SSID", "BSSID", "Signal_dBm", "Frequency_MHz", "Latitude", "Longitude", "Accuracy_m"])

        try:
            while True:
                geo_fix = fetch_telemetry_coordinates()
                network_nodes = sweep_rf_environment()
                current_epoch = time.strftime('%Y-%m-%d %H:%M:%S')
                
                nodes_ingested = 0
                for node in network_nodes:
                    if not node.get("bssid"):
                        continue
                        
                    data_logger.writerow([
                        current_epoch,
                        node.get("ssid", "[BEACON_HIDDEN]"),
                        node.get("bssid"),
                        node.get("rssi", -100),
                        node.get("frequency", 0),
                        geo_fix["lat"],
                        geo_fix["lon"],
                        geo_fix["accuracy"]
                    ])
                    nodes_ingested += 1
                
                raw_file.flush()
                print(f"[\033[94m{current_epoch}\033[0m] Fix: ({geo_fix['lat']}, {geo_fix['lon']}) | Ingested \033[92m{nodes_ingested}\033[0m RF Beacons.")
                time.sleep(12)
                
        except KeyboardInterrupt:
            print("\n[\033[93m!\033[0m] SIGINT received. Halting daemon execution. Data stream preserved.")
            sys.exit(0)

if __name__ == "__main__":
    main()
