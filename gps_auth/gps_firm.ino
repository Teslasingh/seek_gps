/********************************************************
  ESP32 Wi-Fi Config + EEPROM + TinyGPS++ + Device ID
  + HTTP Basic Auth
  -------------------------------------------------
  1) Read stored SSID, PASS, and DeviceID from EEPROM
  2) If connect fails, start AP for reconfig
  3) Once connected, read GPS & send data to server
     (posts JSON data to /gps/api/data with device_id and
      other GPS values)
  4) Uses HTTP Basic Auth with username "fux" & password "458266"
 ********************************************************/
#include <WiFi.h>
#include <WebServer.h>
#include <EEPROM.h>
#include <HTTPClient.h>
#include <TinyGPS++.h>

// ---------------------- EEPROM SETTINGS ----------------------
#define EEPROM_SIZE 128
// We'll store SSID in [0..31], PASS in [32..95], ID in [96..127]

// ---------------------- WEB SERVER ----------------------
WebServer server(80);

// ---------------------- GPS SETTINGS ---------------------
#define RXD2 16     // GPS module TX -> ESP32 pin 16
#define TXD2 17     // GPS module RX -> ESP32 pin 17
#define GPS_BAUD 9600

TinyGPSPlus gps;
HardwareSerial gpsSerial(2); // Use UART2 on ESP32

// ---------------------- GLOBALS -------------------------
String eepromSSID;
String eepromPASS;
String eepromID;  // New: Device ID

// Forward declarations
void launchAP();
bool testWifi();
void createWebServer();
void handleRoot();
void handleSaveCredentials();
void clearEEPROM();
void connectToWiFi();
void readCredentialsFromEEPROM();
void writeCredentialsToEEPROM(const String& newSSID, const String& newPASS, const String& newID);

void setup() {
  Serial.begin(115200);
  delay(200);

  // Initialize EEPROM
  EEPROM.begin(EEPROM_SIZE);

  // Init GPS serial
  gpsSerial.begin(GPS_BAUD, SERIAL_8N1, RXD2, TXD2);
  Serial.println("GPS Serial initialized at 9600 baud rate");

  // Read credentials (including device ID) from EEPROM
  readCredentialsFromEEPROM();

  // Attempt to connect
  if (eepromSSID.length() > 0 && eepromPASS.length() > 0) {
    connectToWiFi();
    if (testWifi()) {
      Serial.print("Wi-Fi connected. IP address: ");
      Serial.println(WiFi.localIP());
      // Proceed to loop() where GPS logic runs
      return;
    } else {
      Serial.println("Connection failed. Starting AP for configuration...");
      launchAP();
    }
  } else {
    Serial.println("No valid credentials in EEPROM. Starting AP...");
    launchAP();
  }
}

void loop() {
  // Always handle incoming requests (if in AP mode)
  server.handleClient();

  // Only run GPS + HTTP logic if we're connected to Wi-Fi
  if (WiFi.status() == WL_CONNECTED) {
    static unsigned long lastSend = 0;
    unsigned long now = millis();

    // Try sending data every 5 seconds
    if (now - lastSend >= 5000) {
      lastSend = now;

      // Gather GPS data for about 1 second
      unsigned long currentMillis = millis();
      while (millis() - currentMillis < 1000) {
        while (gpsSerial.available() > 0) {
          gps.encode(gpsSerial.read());
        }
      }

      // Only if we have a new location
      if (gps.location.isUpdated()) {
        // Build JSON payload with GPS data
        String postData = "{";
        postData += "\"device_id\":\"" + eepromID + "\",";
        postData += "\"lat\":" + String(gps.location.lat(), 6) + ",";
        postData += "\"lng\":" + String(gps.location.lng(), 6) + ",";
        postData += "\"speed\":" + String(gps.speed.kmph()) + ",";
        postData += "\"satellite\":" + String(gps.satellites.value());
        postData += "}";

        Serial.println("Sending data: " + postData);

        // Send to server via HTTP POST
        if (WiFi.status() == WL_CONNECTED) {
          HTTPClient http;
          // Adjust the server address/port as needed.
          // Using the /gps/api/data endpoint as expected by the server.
          String url = "http://anubhav.ddns.net:5000/gps/api/data";
          Serial.println("Requesting: " + url);

          http.begin(url);
          // Set HTTP Basic Auth credentials (username: fux, password: 458266)
          http.setAuthorization("admin", "458266");
          http.addHeader("Content-Type", "application/json");

          int httpResponseCode = http.POST(postData);
          if (httpResponseCode > 0) {
            String response = http.getString();
            Serial.println("Server Response: " + response);
          } else {
            Serial.println("Error sending POST request: " + String(httpResponseCode));
          }
          http.end();
        } else {
          Serial.println("Wi-Fi not connected");
        }
      } else {
        Serial.println("No new GPS location update.");
      }
    } // end if time interval
  }
}

// -----------------------------------------------------
// Start an AP for reconfiguration
// -----------------------------------------------------
void launchAP() {
  WiFi.mode(WIFI_AP);
  WiFi.softAP("Socket"); // open AP, no password
  Serial.print("AP started. IP: ");
  Serial.println(WiFi.softAPIP());
  createWebServer();
}

// -----------------------------------------------------
// Try to connect with stored credentials
// -----------------------------------------------------
void connectToWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(eepromSSID.c_str(), eepromPASS.c_str());
  Serial.println();
  Serial.print("Connecting to Wi-Fi with SSID: ");
  Serial.println(eepromSSID);
}

// -----------------------------------------------------
// Test WiFi connection for ~10 seconds
// -----------------------------------------------------
bool testWifi() {
  int count = 0;
  while (WiFi.status() != WL_CONNECTED && count < 2000) {
    delay(200);
    Serial.print(".");
    count++;
  }
  Serial.println();
  return (WiFi.status() == WL_CONNECTED);
}

// -----------------------------------------------------
// Configure WebServer for AP mode
// -----------------------------------------------------
void createWebServer() {
  server.on("/", HTTP_GET, handleRoot);
  server.on("/save", HTTP_POST, handleSaveCredentials);
  server.on("/clear", HTTP_GET, [](){
    server.send(200, "text/plain", "EEPROM Cleared. Restarting...");
    delay(1000);
    ESP.restart();
  });
  server.begin();
  Serial.println("WebServer started on port 80.");
}

// -----------------------------------------------------
// Root handler: HTML form for new Wi-Fi + device ID
// -----------------------------------------------------
void handleRoot() {
  String html = "<!DOCTYPE html><html>"
                "<head><title>Wi-Fi Config</title></head>"
                "<body>"
                "<h1>Enter Wi-Fi Credentials & Device ID</h1>"
                "<form action='/save' method='POST'>"
                "<label>SSID:</label> <input type='text' name='ssid'><br><br>"
                "<label>PASS:</label> <input type='password' name='pass'><br><br>"
                "<label>Device ID:</label> <input type='text' name='id'><br><br>"
                "<input type='submit' value='Save &amp; Reboot'>"
                "</form>"
                "<p>Or <a href='/clear'>Clear EEPROM</a></p>"
                "</body></html>";

  server.send(200, "text/html", html);
}

// -----------------------------------------------------
// Save new SSID, PASS, and ID to EEPROM, reboot
// -----------------------------------------------------
void handleSaveCredentials() {
  clearEEPROM();
  String newSSID = server.arg("ssid");
  String newPASS = server.arg("pass");
  String newID   = server.arg("id"); // new field

  if (newSSID.length() > 0 && newPASS.length() > 0 && newID.length() > 0) {
    Serial.println("Received new credentials:");
    Serial.println("SSID: " + newSSID);
    Serial.println("PASS: " + newPASS);
    Serial.println("ID:   " + newID);

    writeCredentialsToEEPROM(newSSID, newPASS, newID);

    server.send(200, "text/plain", "Credentials saved. Rebooting...");
    delay(1000);
    ESP.restart();
  } else {
    server.send(400, "text/plain", "Invalid SSID, Password, or Device ID.");
  }
}

// -----------------------------------------------------
// Helpers
// -----------------------------------------------------
void clearEEPROM() {
  for (int i = 0; i < EEPROM_SIZE; i++) {
    EEPROM.write(i, 0);
  }
  EEPROM.commit();
  Serial.println("EEPROM cleared.");
}

// Read SSID, PASS, ID from EEPROM
void readCredentialsFromEEPROM() {
  // SSID in [0..31]
  eepromSSID = "";
  for (int i = 0; i < 32; i++) {
    char c = char(EEPROM.read(i));
    if (c == 0 || c == 255) break;
    eepromSSID += c;
  }

  // PASS in [32..95]
  eepromPASS = "";
  for (int i = 32; i < 96; i++) {
    char c = char(EEPROM.read(i));
    if (c == 0 || c == 255) break;
    eepromPASS += c;
  }

  // ID in [96..127]
  eepromID = "";
  for (int i = 96; i < 128; i++) {
    char c = char(EEPROM.read(i));
    if (c == 0 || c == 255) break;
    eepromID += c;
  }

  Serial.print("Stored SSID: "); Serial.println(eepromSSID);
  Serial.print("Stored PASS: "); Serial.println(eepromPASS);
  Serial.print("Stored ID:   "); Serial.println(eepromID);
}

// Write SSID, PASS, ID to EEPROM
void writeCredentialsToEEPROM(const String& newSSID, const String& newPASS, const String& newID) {
  // Clear relevant portion
  for (int i = 0; i < EEPROM_SIZE; i++) {
    EEPROM.write(i, 0);
  }

  // Write SSID in [0..31]
  for (int i = 0; i < newSSID.length() && i < 32; i++) {
    EEPROM.write(i, newSSID[i]);
  }

  // Write PASS in [32..95]
  for (int i = 0; i < newPASS.length() && i < 64; i++) {
    EEPROM.write(32 + i, newPASS[i]);
  }

  // Write ID in [96..127]
  for (int i = 0; i < newID.length() && i < 32; i++) {
    EEPROM.write(96 + i, newID[i]);
  }

  EEPROM.commit();
  Serial.println("EEPROM updated with new credentials (SSID, PASS, ID).");
}
