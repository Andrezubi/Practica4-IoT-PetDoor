


#include <Arduino.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <SPI.h>
#include <time.h>

#include "RFID.h"
#include "SmoothServo.h"

// ─────────────────────────────────────────────────────────────────────────────
// Network & AWS config
// ─────────────────────────────────────────────────────────────────────────────
const char* WIFI_SSID   = "Flia.zubieta_s";      
const char* WIFI_PASS   = "Zubieta1234";         
const char* MQTT_BROKER = "a2z78sujrz3n3i-ats.iot.us-east-1.amazonaws.com"; 
const int   MQTT_PORT   = 8883;
const char* CLIENT_ID   = "pet_door_esp32";
const char* THING_NAME  = "pet_door_esp32";   

// Shadow MQTT topics
const char* TOPIC_UPDATE       = "$aws/things/pet_door_esp32/shadow/update";
const char* TOPIC_DELTA        = "$aws/things/pet_door_esp32/shadow/update/delta";
const char* TOPIC_GET          = "$aws/things/pet_door_esp32/shadow/get";
const char* TOPIC_GET_ACCEPTED = "$aws/things/pet_door_esp32/shadow/get/accepted";

// ─────────────────────────────────────────────────────────────────────────────
// Certificates 
// ─────────────────────────────────────────────────────────────────────────────
const char AMAZON_ROOT_CA1[] PROGMEM = R"EOF(
-----BEGIN CERTIFICATE-----
MIIDQTCCAimgAwIBAgITBmyfz5m/jAo54vB4ikPmljZbyjANBgkqhkiG9w0BAQsF
ADA5MQswCQYDVQQGEwJVUzEPMA0GA1UEChMGQW1hem9uMRkwFwYDVQQDExBBbWF6
b24gUm9vdCBDQSAxMB4XDTE1MDUyNjAwMDAwMFoXDTM4MDExNzAwMDAwMFowOTEL
MAkGA1UEBhMCVVMxDzANBgNVBAoTBkFtYXpvbjEZMBcGA1UEAxMQQW1hem9uIFJv
b3QgQ0EgMTCCASIwDQYJKoZIhvcNAQEBBQADggEPADCCAQoCggEBALJ4gHHKeNXj
ca9HgFB0fW7Y14h29Jlo91ghYPl0hAEvrAIthtOgQ3pOsqTQNroBvo3bSMgHFzZM
9O6II8c+6zf1tRn4SWiw3te5djgdYZ6k/oI2peVKVuRF4fn9tBb6dNqcmzU5L/qw
IFAGbHrQgLKm+a/sRxmPUDgH3KKHOVj4utWp+UhnMJbulHheb4mjUcAwhmahRWa6
VOujw5H5SNz/0egwLX0tdHA114gk957EWW67c4cX8jJGKLhD+rcdqsq08p8kDi1L
93FcXmn/6pUCyziKrlA4b9v7LWIbxcceVOF34GfID5yHI9Y/QCB/IIDEgEw+OyQm
jgSubJrIqg0CAwEAAaNCMEAwDwYDVR0TAQH/BAUwAwEB/zAOBgNVHQ8BAf8EBAMC
AYYwHQYDVR0OBBYEFIQYzIU07LwMlJQuCFmcx7IQTgoIMA0GCSqGSIb3DQEBCwUA
A4IBAQCY8jdaQZChGsV2USggNiMOruYou6r4lK5IpDB/G/wkjUu0yKGX9rbxenDI
U5PMCCjjmCXPI6T53iHTfIUJrU6adTrCC2qJeHZERxhlbI1Bjjt/msv0tadQ1wUs
N+gDS63pYaACbvXy8MWy7Vu33PqUXHeeE6V/Uq2V8viTO96LXFvKWlJbYK8U90vv
o/ufQJVtMVT8QtPHRh8jrdkPSHCa2XV4cdFyQzR1bldZwgJcJmApzyMZFo6IQ6XU
5MsI+yMRQ+hDKXJioaldXgjUkK642M4UwtBV8ob2xJNDd2ZhwLnoQdeXeGADbkpy
rqXRfboQnoZsG4q5WTP468SQvvG5
-----END CERTIFICATE-----
)EOF";

const char CERTIFICATE[] PROGMEM = R"KEY(
-----BEGIN CERTIFICATE-----
MIIDWTCCAkGgAwIBAgIUZTFpScN1ghjBAwRh5XaSHdmCBc8wDQYJKoZIhvcNAQEL
BQAwTTFLMEkGA1UECwxCQW1hem9uIFdlYiBTZXJ2aWNlcyBPPUFtYXpvbi5jb20g
SW5jLiBMPVNlYXR0bGUgU1Q9V2FzaGluZ3RvbiBDPVVTMB4XDTI2MDUxMDA4NTMx
N1oXDTQ5MTIzMTIzNTk1OVowHjEcMBoGA1UEAwwTQVdTIElvVCBDZXJ0aWZpY2F0
ZTCCASIwDQYJKoZIhvcNAQEBBQADggEPADCCAQoCggEBANBJ6oZa1l36ult0Yv2m
KQyww4Jk3xLIoH6cQWtsdOusucwUY4FvII1FF+I/VpLycQD5AEuRXN/w2o/o8srH
TZmn8DknKaiRwZJP0uwqX0d7RMTG/Xadd4VyaAiIpag35Sur5bhNpkxb7dOuTxs/
hbq2qqcZ/1AMT1uXSm31g6pvR8wPD7KVMstnZ3q528y/K+eGYd/FOILgTT4yQLkr
1DVKWVAS+hmabD/sUy7cJkkRc/AtmE29RRP2rdoDBcOAoPIqy4mHI/ehOVGqnlES
0AV3a/bu5ef1BTnwjqWOc6GSYR3MpXraQ+zFiDNRAUuUrw8LOwDi+fLg5HLKxoVz
uMMCAwEAAaNgMF4wHwYDVR0jBBgwFoAUFdd5Ers6L4kzROkdp/C7aQaY0WYwHQYD
VR0OBBYEFJeo8rBiuMipvVkrLsnrgF8dF7OwMAwGA1UdEwEB/wQCMAAwDgYDVR0P
AQH/BAQDAgeAMA0GCSqGSIb3DQEBCwUAA4IBAQC8Pc3gCDsy36Tm7UnL2mkOy8/U
0n0CTyrnBiai0w7/GFM2k35Fyr2CFHM3gfVNNbyG5xoco/87LZhdCBJt7RKx9B9M
O44w/818P9xqtVUqQ0C28m+r5o8xox+3B1GyEIuoHHiW9Ct0u4ZMhexe99rxgoI0
GAWogkMmLAZ4UTYUxi4iHZ7dn4C+d54D+fDRD7XroddEm4gyZC36UA1luYVdVPBH
FERoSQDAuQ14CO8gyh/3is6lfh0UCG+OGMfaBc9ikeAle9a4fC+b8l3wfedNFUA3
8ZsnAP3BHC2mC5VrdwHjM9rqFZVR22X3PjzWIZ4lPu1xGFG2y4ZFkOvdlgbi
-----END CERTIFICATE-----
)KEY";

const char PRIVATE_KEY[] PROGMEM = R"KEY(
-----BEGIN RSA PRIVATE KEY-----
MIIEpQIBAAKCAQEA0EnqhlrWXfq6W3Ri/aYpDLDDgmTfEsigfpxBa2x066y5zBRj
gW8gjUUX4j9WkvJxAPkAS5Fc3/Daj+jyysdNmafwOScpqJHBkk/S7CpfR3tExMb9
dp13hXJoCIilqDflK6vluE2mTFvt065PGz+Furaqpxn/UAxPW5dKbfWDqm9HzA8P
spUyy2dnernbzL8r54Zh38U4guBNPjJAuSvUNUpZUBL6GZpsP+xTLtwmSRFz8C2Y
Tb1FE/at2gMFw4Cg8irLiYcj96E5UaqeURLQBXdr9u7l5/UFOfCOpY5zoZJhHcyl
etpD7MWIM1EBS5SvDws7AOL58uDkcsrGhXO4wwIDAQABAoIBAAE+H6cTjanb4BbB
mAGZZy9LMq9peKc9CTAYMI+6guwRCL699GYGSrRtEBpqdFLGHYR699R7lolDf5pS
MnihPcZH6Tf+EtKNpBECZui/y/e6NYvTABogEGF8cEB0yEA7rSNYkDNMS0yzU7Tq
mlA4TczyYAxFLG/G0wZh3bDQQSvYIVqxo540sne44cIsfVTdILhtswrwlnLeXonD
uK3ec1umN8mxRBdPCq1g7meQpnh4MCh3RYyB0/s9I6osrdHU1FaJVXgEQV9OEZJL
6dfiXBFB832pIUQNUIjDBRlbsSsZKFZD5LEmpn6+jvb3vNhY8fdpIRVjmRNCvBiT
dZUHiMkCgYEA+wYt0O4whtPiG0ot1P9bKgGtjyK6GaTSzd2JU8OE/c8cSwUMucDb
grwhWRJxXOIQjwZFgvd1S20U5BPSt8Mg4iD4kQ34FbVdNkyaKSOvp8vLebOls17L
JkjVExD6BaX5U18Q6nCIxatLMHydUCRNPC/pqDnP/aRqbePP1Y7wCVcCgYEA1Grg
YuD+v1WSu3UhoRZre1BLF7izyXQa+wjBg9Dm2kMaIK8pv6SbkNnRqpBEyfqKobPv
7jKtyx9GBnVuggu785xgtf9XJh33fTcpPveRBR7QxqZmDcBvixYQcYMJ78HEor88
vaFWTttOAuioB4WynoFxIIPYaRWgIeUKjR+vrHUCgYEAif05jlKBRnyPHKVIUIAW
4x6NA9P5LUOXxibz6KHgJ42EZhDej/XeNR2pz0b+Hir/I0A1UesqBU5vX3kuKmoP
V378ZPCi4XwTQ1gUnmzJkJnMvpfsjI+daOw8hQCeECDOz+/AYr99z/t7l6nI6Fcs
RduovBsbpLiO8N18UE8E0H0CgYEAhOUg4Xv2pWo6VQGhOpE2SX4gnQS3pq/3OVtv
BrMp2x/kNtKgAgBQO72rCVUdVGhlV2mmEJawWMaGHwBVVRNWUcFiWDsaIQTalAJw
0a49ksCGyeHNM4lTv+bb/siG7PODvHZ83/8Sal+WXQeGKL6i07wUNM2IFaar+si7
YzORywkCgYEAhThPCxyO7KxqAQAHq2tQv2/sm+qsjIxL3qv1Zo9Mto1ipC6l4qAt
M7AVOAZ/uS9gG0C5NW2sszMQ3HBLTFAzNcc5ERc9gmA8PKoLoYiCRU/0KT6C8bbo
4h1fv3qzkq7lx2y/9b+ymhJ0cPJcH1UXI6cX/JIWstC9cpkk1xti38k=
-----END RSA PRIVATE KEY-----
)KEY";

// ─────────────────────────────────────────────────────────────────────────────
// Pin definitions
// ─────────────────────────────────────────────────────────────────────────────
#define RFID_SS_PIN   5
#define RFID_RST_PIN  4
#define SERVO_PIN     13

// ─────────────────────────────────────────────────────────────────────────────
// Door angle constants — only the main knows what angles mean
// ─────────────────────────────────────────────────────────────────────────────
#define DOOR_ANGLE_CLOSED  0
#define DOOR_ANGLE_OPEN    90

// ─────────────────────────────────────────────────────────────────────────────
// Hardware objects
// ─────────────────────────────────────────────────────────────────────────────
RFID         rfid(RFID_SS_PIN, RFID_RST_PIN);

SmoothServo  servo(SERVO_PIN, DOOR_ANGLE_CLOSED, /*stepDeg=*/2, /*intervalMs=*/15);

WiFiClientSecure wifiClient;
PubSubClient     mqttClient(wifiClient);

// ─────────────────────────────────────────────────────────────────────────────
// Runtime state
// ─────────────────────────────────────────────────────────────────────────────
String        currentMode     = "auto";
unsigned int  openDurationSec = 30;
unsigned long openedAt        = 0;
bool          autoCloseArmed  = false;
bool          needsReport     = false;

StaticJsonDocument<1024> petsDoc;

// ─────────────────────────────────────────────────────────────────────────────
// Door helpers — the main interprets servo angles as door states
// ─────────────────────────────────────────────────────────────────────────────

bool doorIsOpen()   { return servo.getCurrentAngle() >= DOOR_ANGLE_OPEN   && servo.isIdle(); }
bool doorIsClosed() { return servo.getCurrentAngle() <= DOOR_ANGLE_CLOSED && servo.isIdle(); }
bool doorIsMoving() { return servo.isMoving(); }

const char* getDoorStateStr() {
  if (servo.isMoving())
    return (servo.getTargetAngle() >= DOOR_ANGLE_OPEN) ? "opening" : "closing";
  if (doorIsOpen())   return "open";
  if (doorIsClosed()) return "closed";
  return "unknown";
}

const char* getMotorStateStr() {
  return servo.isMoving() ? "running" : "idle";
}

void commandOpen() {

  if (doorIsOpen()) {
    Serial.println("[DOOR] Already open, ignoring.");
    return;
  }

  Serial.println("[DOOR] → OPEN");

  servo.moveTo(DOOR_ANGLE_OPEN);

  openedAt = millis();

  // SOLO activar auto close en modo auto
  if (currentMode == "auto") {
    autoCloseArmed = (openDurationSec > 0);
  }
  else {
    autoCloseArmed = false;
  }

  needsReport = true;
}

void commandClose() {
  if (doorIsClosed()) {
    Serial.println("[DOOR] Already closed, ignoring.");
    return;
  }
  Serial.println("[DOOR] → CLOSE");
  servo.moveTo(DOOR_ANGLE_CLOSED);
  autoCloseArmed = false;
  needsReport    = true;
}

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────




String getISOTimestamp() {
  struct tm timeinfo;
  if (!getLocalTime(&timeinfo)) return "1970-01-01T00:00:00Z";
  char buf[25];
  strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M:%SZ", &timeinfo);
  return String(buf);
}

String findPetByTag(const String& uid) {
  JsonArray pets = petsDoc["pets"].as<JsonArray>();
  
  Serial.print("[AUTH] Looking for tag: '");
  Serial.print(uid);
  Serial.print("' in pets array (count=");
  Serial.print(pets.size());
  Serial.println(")");
  
  for (JsonObject pet : pets) {
    String petTag = pet["tag"].as<String>();
    String petName = pet["name"].as<String>();
    
    Serial.print("[AUTH]   Comparing '");
    Serial.print(uid);
    Serial.print("' vs '");
    Serial.print(petTag);
    Serial.print("' → ");
    
    if (petTag == uid) {
      Serial.println("MATCH!");
      Serial.print("[AUTH] Matched → ");
      Serial.println(petName);
      return petName;
    } else {
      Serial.println("no match");
    }
  }
  
  Serial.print("[AUTH] Unknown tag: ");
  Serial.println(uid);
  return "";
}

// ─────────────────────────────────────────────────────────────────────────────
// Shadow publishing
// ─────────────────────────────────────────────────────────────────────────────

void publishReport(const String& lastTag = "", const String& lastPet = "") {
  StaticJsonDocument<512> doc;
  JsonObject reported = doc["state"]["reported"].to<JsonObject>();

  reported["mode"]          = currentMode;
  reported["door_state"]    = getDoorStateStr();
  reported["motor_state"]   = getMotorStateStr();
  reported["open_duration"] = openDurationSec;
  reported["tag_present"]   = rfid.isTagPresent();

  if (lastTag.length() > 0) {
    reported["last_tag"]     = lastTag;
    reported["last_pet"]     = lastPet;
    reported["last_open_at"] = getISOTimestamp();
  }

  char buffer[512];
  serializeJson(doc, buffer);
  Serial.print("[MQTT] Report → ");
  Serial.println(buffer);
  mqttClient.publish(TOPIC_UPDATE, buffer);
  needsReport = false;
}

// ─────────────────────────────────────────────────────────────────────────────
// Delta handler
// ─────────────────────────────────────────────────────────────────────────────

void applyDelta(JsonObject delta) {
  bool changed = false;

  if (delta.containsKey("mode")) {

    String newMode = delta["mode"].as<String>();

    if(newMode != currentMode){

      Serial.print("[DELTA] mode: ");
      Serial.print(currentMode);
      Serial.print(" → ");
      Serial.println(newMode);

      currentMode = newMode;
      changed = true;
    }

    if (currentMode == "open") {

      autoCloseArmed = false;
      commandOpen();

    }
    else if (currentMode == "closed") {

      autoCloseArmed = false;
      commandClose();

    }
    else if (currentMode == "auto") {

      // si la puerta ya está abierta,
      // empezar timer automático
      if (doorIsOpen()) {

        openedAt = millis();
        autoCloseArmed = (openDurationSec > 0);

        Serial.println("[AUTO] Auto-close rearmed.");
      }
    }
}

  if (delta.containsKey("open_duration")) {
    unsigned int newDuration= delta["open_duration"].as<unsigned int>();
    if(newDuration!= openDurationSec){
      openDurationSec = delta["open_duration"].as<unsigned int>();
      Serial.print("[DELTA] open_duration → ");
      Serial.println(openDurationSec);
      changed = true;

    }
    
  }

  if (delta.containsKey("pets")) {
    petsDoc["pets"] = delta["pets"];
    Serial.print("[DELTA] pets updated, count=");
    Serial.println(delta["pets"].size());
  }

  if (changed) needsReport = true;
}

// ─────────────────────────────────────────────────────────────────────────────
// MQTT callback
// ─────────────────────────────────────────────────────────────────────────────

void mqttCallback(char* topic, byte* payload, unsigned int length) {
  String topicStr(topic);
  Serial.print("[MQTT] Received: ");
  Serial.println(topicStr);

  StaticJsonDocument<1024> doc;
  DeserializationError err = deserializeJson(doc, payload, length);
  if (err) {
    Serial.print("[MQTT] JSON error: ");
    Serial.println(err.c_str());
    return;
  }


  
  if (topicStr == TOPIC_DELTA) {
    applyDelta(doc["state"].as<JsonObject>());

  } else if (topicStr == TOPIC_GET_ACCEPTED) {
    Serial.println("[MQTT] Full shadow received, syncing desired...");
    applyDelta(doc["state"]["desired"].as<JsonObject>());

    if (!doc["state"]["desired"].containsKey("pets") &&
        doc["state"]["reported"].containsKey("pets")) {
      petsDoc["pets"] = doc["state"]["reported"]["pets"];  // ← FIX: ahora lee de reported
      Serial.println("[MQTT] Pets restored from reported.");
    }
    else if (doc["state"]["desired"].containsKey("pets")) {  // ← más claro
      petsDoc["pets"] = doc["state"]["desired"]["pets"];
      Serial.println("[MQTT] Pets loaded from desired.");
    }
  }

}

// ─────────────────────────────────────────────────────────────────────────────
// WiFi & MQTT
// ─────────────────────────────────────────────────────────────────────────────

void setupWiFi() {
  Serial.print("[WIFI] Connecting to ");
  Serial.println(WIFI_SSID);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED) { delay(500); Serial.print("."); }
  Serial.print("\n[WIFI] Connected. IP: ");
  Serial.println(WiFi.localIP());

  configTime(0, 0, "pool.ntp.org", "time.nist.gov");
  Serial.print("[NTP] Syncing");
  struct tm ti;
  int attempts=0;
  while(!getLocalTime(&ti)&&attempts<20){
    delay(500);
    Serial.print(".");
    attempts++;
  }
  if(attempts>=20){
    Serial.println("\n [NTP]Failed -this will cause tls errors");
  }
  else{ Serial.println("OK");}


  while (!getLocalTime(&ti)) { delay(500); Serial.print("."); 
  Serial.println(" OK");
  }
}


void reconnect() {
  while (!mqttClient.connected()) {
    Serial.print("[MQTT] Connecting...");
    if (mqttClient.connect(CLIENT_ID)) {
      Serial.println(" connected.");
      mqttClient.subscribe(TOPIC_DELTA);
      mqttClient.subscribe(TOPIC_GET_ACCEPTED);
      mqttClient.publish(TOPIC_GET, "{}");
      Serial.println("[MQTT] Shadow requested.");
    } else {
      Serial.print(" failed rc=");
      Serial.print(mqttClient.state());
      Serial.println(", retry in 5s...");
      delay(5000);
    }
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// setup()
// ─────────────────────────────────────────────────────────────────────────────

void setup() {
  Serial.begin(115200);
  Serial.println("\n[SYS] Pet Door starting...");

  setupWiFi();
  wifiClient.setInsecure();
  wifiClient.setCACert(AMAZON_ROOT_CA1);
  wifiClient.setCertificate(CERTIFICATE);
  wifiClient.setPrivateKey(PRIVATE_KEY);

  Serial.println("[TLS] Testing raw TLS connection...");
  if (wifiClient.connect(MQTT_BROKER, MQTT_PORT)) {
    Serial.println("[TLS] ✓ TLS handshake SUCCESS");
    wifiClient.stop();
  } else {
    Serial.print("[TLS] ✗ TLS failed, error: ");
    char errbuf[100];

    Serial.println(wifiClient.lastError(errbuf,sizeof(errbuf)));
  }

  mqttClient.setServer(MQTT_BROKER, MQTT_PORT);
  mqttClient.setKeepAlive(60);
  mqttClient.setSocketTimeout(30);
  mqttClient.setCallback(mqttCallback);
  mqttClient.setBufferSize(1024);

  SPI.begin();
  rfid.init();
  servo.init();

  Serial.println("[SYS] Setup complete.");
}

// ─────────────────────────────────────────────────────────────────────────────
// loop()
// ─────────────────────────────────────────────────────────────────────────────

void loop() {
  
  if(WiFi.status() != WL_CONNECTED) setupWiFi();

//  ─────────────────────────────────────────────────────────────
  if (!mqttClient.connected()) reconnect();
  mqttClient.loop();

  // ── Servo smooth step ──────────────────────────────────────────────────────
  bool servoArrived = servo.update();
  if (servoArrived) {
    Serial.print("[DOOR] Settled → ");
    Serial.println(getDoorStateStr());
    needsReport = true;
  }

  // ── RFID polling ──────────────────────────────────────────────────────────
  bool rfidChanged = rfid.update();

  if (rfidChanged) {
    if (rfid.getState() == RFID::TAG_PRESENT) {
      String uid = rfid.getCurrentUID();

      if (currentMode == "auto" && !doorIsOpen() && !doorIsMoving()) {
        String petName = findPetByTag(uid);
        if (petName.length() > 0 && petName!="Unknown") {
          commandOpen();
          publishReport(uid, petName);
          needsReport = false;
        } else {
          needsReport = true; // report unknown tag_present
        }
      }

    } else if (rfid.getState() == RFID::TAG_REMOVED) {
      Serial.println("[RFID] Tag gone.");
      needsReport = true;
    }
  }

  // ── Auto-close timer ──────────────────────────────────────────────────────
  if (autoCloseArmed && doorIsOpen()) {
    if ((millis() - openedAt) / 1000UL >= openDurationSec) {
      Serial.print("[AUTO] Timer (");
      Serial.print(openDurationSec);
      Serial.println("s) expired — closing.");
      commandClose();
    }
  }

  // ── Pending report ─────────────────────────────────────────────────────────
  if (needsReport && mqttClient.connected()) {
    String petName = findPetByTag(rfid.getCurrentUID());
    publishReport(rfid.getCurrentUID(),petName);

  }
}

