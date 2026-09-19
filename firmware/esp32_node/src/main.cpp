#include <Arduino.h>
#include <ArduinoJson.h>
#include <PubSubClient.h>
#include <WiFi.h>
#include <Wire.h>
#include <Adafruit_PWMServoDriver.h>
#include <Preferences.h>
#include "secrets.h"
#include "node_config.h"

// This firmware never accepts raw GPIO/channel/PWM commands. The installed
// configuration maps stable MTOS asset IDs to local outputs.
WiFiClient wifi;
PubSubClient mqtt(wifi);
Adafruit_PWMServoDriver pwm(0x40);
Preferences positions;
String bootId, producerSession;
uint32_t shiftImage = 0;
uint64_t epochBaseMs = 0;
uint32_t epochBaseMillis = 0;

enum Runner { IDLE, SERVO_SWEEP, SERVO_SETTLE, SIGNAL_BREAK, MACHINE_CONTACT, MACHINE_WAIT };
Runner runner = IDLE;
String executionId, commandHash, activeAsset, targetValue;
uint32_t deadline = 0;
int servoIndex = 0, servoStep = 0, servoTarget = 0, servoCurrent = 0;
const TurnoutMap *activeTurnout = nullptr;
const SignalMap *activeSignal = nullptr;

struct Dedup { String id, hash, state; uint32_t expires; };
Dedup dedup[64];

String baseTopic() { return "mtos/v1/nodes/" + String(MTOS_NODE_ID); }
uint64_t currentUnixMs() {
  return epochBaseMs ? epochBaseMs + (uint32_t)(millis() - epochBaseMillis) : 0;
}
void shiftLatch() {
  digitalWrite(MTOS_SHIFT_LATCH_PIN, LOW);
  for (int byteIndex = MTOS_SHIFT_REGISTER_COUNT - 1; byteIndex >= 0; --byteIndex)
    shiftOut(MTOS_SHIFT_DATA_PIN, MTOS_SHIFT_CLOCK_PIN, MSBFIRST, (shiftImage >> (byteIndex * 8)) & 0xff);
  digitalWrite(MTOS_SHIFT_LATCH_PIN, HIGH);
}
void publishJson(const String &suffix, JsonDocument &doc, bool retained=false) {
  char payload[1536]; size_t size = serializeJson(doc, payload, sizeof(payload));
  mqtt.publish((baseTopic() + suffix).c_str(), payload, size, retained);
}
void publishEvent(const char *state, const char *reason=nullptr) {
  JsonDocument doc;
  doc["schema"] = "mtos.mc-event.v1"; doc["node_id"] = MTOS_NODE_ID;
  doc["boot_id"] = bootId; doc["producer_session_id"] = producerSession;
  doc["execution_id"] = executionId; doc["payload_hash"] = commandHash;
  doc["state"] = state; if (reason) doc["result"]["reason"] = reason;
  publishJson("/events", doc);
}
void publishStatus() {
  JsonDocument doc;
  doc["node_id"] = MTOS_NODE_ID; doc["boot_id"] = bootId;
  doc["firmware"] = MTOS_FIRMWARE_VERSION;
  doc["configuration_revision"] = MTOS_CONFIGURATION_REVISION;
  doc["producer_session_id"] = producerSession; doc["availability"] = "online";
  doc["detail"]["runner"] = (int)runner;
  publishJson("/status", doc, true);
}
const TurnoutMap *turnout(const String &id) { for (auto &item : TURNOUTS) if (id == item.id) return &item; return nullptr; }
const SignalMap *signal(const String &id) { for (auto &item : SIGNALS) if (id == item.id) return &item; return nullptr; }
void serialCommissioning() {
  if (!Serial.available()) return;
  String line=Serial.readStringUntil('\n'); line.trim();
  int first=line.indexOf(' '), second=first<0?-1:line.indexOf(' ',first+1);
  String verb=first<0?line:line.substring(0,first);
  String asset=first<0?"":(second<0?line.substring(first+1):line.substring(first+1,second));
  String value=second<0?"":line.substring(second+1); asset.trim(); value.trim();
  if (runner!=IDLE) { Serial.println("ERR actuator busy"); return; }
  if (verb=="position" && turnout(asset) && (value=="straight" || value=="diverging")) {
    positions.putString(asset.c_str(),value); Serial.println("OK position recorded");
  } else if (verb=="clear" && turnout(asset)) {
    positions.remove(asset.c_str()); Serial.println("OK position cleared");
  } else if (verb=="position" && turnout(asset)) {
    String stored=positions.getString(asset.c_str(),"");
    Serial.println(stored.length()?stored:"unknown");
  } else Serial.println("ERR use: position T001 [straight|diverging] | clear T001");
}
bool hasDedupCapacity() {
  for (auto &item : dedup)
    if (!item.id.length() || (int32_t)(millis()-item.expires)>0) return true;
  return false;
}
bool remember(const String &id, const String &hash, const String &state, uint32_t expires) {
  for (auto &item : dedup) if (!item.id.length() || (int32_t)(millis()-item.expires)>0) { item={id,hash,state,expires}; return true; }
  return false;
}
Dedup *known(const String &id) { for (auto &item : dedup) if (item.id == id && (int32_t)(item.expires-millis())>0) return &item; return nullptr; }
void finish(const char *state, const char *reason=nullptr) {
  publishEvent(state, reason); remember(executionId, commandHash, state, millis()+60000);
  if (activeTurnout) pwm.setPWM(servoCurrent, 0, 4096);
  digitalWrite(MTOS_MACHINE_RELAY_PIN, LOW);
  runner=IDLE; executionId=""; activeTurnout=nullptr; activeSignal=nullptr;
}
void acceptCommand(JsonDocument &doc) {
  String schema=doc["schema"]|"", node=doc["node_id"]|"", boot=doc["boot_id"]|"";
  if (schema == "mtos.mc-session.v1") {
    uint64_t supplied=doc["server_unix_ms"]|0ULL;
    if (node == MTOS_NODE_ID && boot == bootId && supplied>1700000000000ULL) {
      producerSession=String(doc["producer_session_id"]|""); epochBaseMs=supplied;
      epochBaseMillis=millis(); publishStatus();
    }
    return;
  }
  String id=doc["execution_id"]|"", hash=doc["payload_hash"]|"";
  Dedup *prior=known(id); if (prior) { executionId=id; commandHash=hash; publishEvent(prior->hash==hash?prior->state.c_str():"rejected", prior->hash==hash?nullptr:"duplicate_payload"); executionId=""; return; }
  executionId=id; commandHash=hash;
  if (!id.length() || !hash.length()) { publishEvent("rejected","identity_required"); executionId=""; return; }
  if (!hasDedupCapacity()) { publishEvent("rejected","dedup_capacity"); executionId=""; return; }
  if (runner!=IDLE) { publishEvent("rejected","busy"); executionId=""; return; }
  if (!producerSession.length() || node!=MTOS_NODE_ID || boot!=bootId || String(doc["producer_session_id"]|"")!=producerSession) { publishEvent("rejected","session_mismatch"); executionId=""; return; }
  if ((int)(doc["configuration_revision"]|0)!=MTOS_CONFIGURATION_REVISION) { publishEvent("rejected","configuration_mismatch"); executionId=""; return; }
  uint64_t expires=doc["expires_unix_ms"]|0ULL;
  if (!expires || !currentUnixMs() || currentUnixMs()>expires) { publishEvent("rejected","expired_or_clock_invalid"); executionId=""; return; }
  activeAsset=String(doc["asset_id"]|""); targetValue=String(doc["value"]|""); String operation=doc["operation"]|"";
  if (operation=="turnout.set" && targetValue!="straight" && targetValue!="diverging") { publishEvent("rejected","unsupported_value"); executionId=""; return; }
  if (operation=="signal.set" && targetValue!="stop" && targetValue!="slow" && targetValue!="go") { publishEvent("rejected","unsupported_value"); executionId=""; return; }
  if (operation=="machine.execute" && targetValue!="operate") { publishEvent("rejected","unsupported_value"); executionId=""; return; }
  publishEvent("accepted"); publishEvent("started");
  if (operation=="turnout.set" && (activeTurnout=turnout(activeAsset))) {
    String prior=positions.getString(activeAsset.c_str(),"");
    if(prior!="straight" && prior!="diverging"){finish("failed","position_unknown_requires_commissioning");return;}
    servoIndex=0; servoCurrent=activeTurnout->servo[0].channel; servoStep=0;
    servoStep=prior=="straight"?activeTurnout->servo[0].straight:activeTurnout->servo[0].diverging;
    servoTarget=targetValue=="straight"?activeTurnout->servo[0].straight:activeTurnout->servo[0].diverging;
    runner=SERVO_SWEEP; deadline=millis()+2500;
  } else if (operation=="signal.set" && (activeSignal=signal(activeAsset))) {
    if (targetValue=="slow" && !activeSignal->threeAspect) { finish("failed","unsupported_value"); return; }
    shiftImage &= ~(activeSignal->stopMask|activeSignal->slowMask|activeSignal->goMask); shiftLatch(); runner=SIGNAL_BREAK; deadline=millis()+50;
  } else if (operation=="machine.execute" && activeAsset==WATER_TANK_ID && targetValue=="operate") {
    digitalWrite(MTOS_MACHINE_RELAY_PIN,HIGH); runner=MACHINE_CONTACT; deadline=millis()+WATER_TANK_CONTACT_MS;
  } else finish("failed","unknown_asset_or_operation");
}
void mqttMessage(char *topic, byte *payload, unsigned int length) {
  JsonDocument doc; if (deserializeJson(doc,payload,length)) return; acceptCommand(doc);
}
void connectNetwork() {
  static uint32_t wifiAttempt=0,mqttAttempt=0; uint32_t now=millis();
  if (WiFi.status()!=WL_CONNECTED) {
    if (!wifiAttempt || now-wifiAttempt>=5000) { wifiAttempt=now; WiFi.begin(MTOS_WIFI_SSID,MTOS_WIFI_PASSWORD); }
    return;
  }
  if (!mqtt.connected()) {
    if (mqttAttempt && now-mqttAttempt<2000) return; mqttAttempt=now;
    String will=baseTopic()+"/availability";
    if (mqtt.connect(("mtos-"+String(MTOS_NODE_ID)).c_str(),MTOS_MQTT_USERNAME,MTOS_MQTT_PASSWORD,will.c_str(),1,true,"{\"availability\":\"offline\"}")) {
      mqtt.subscribe((baseTopic()+"/commands").c_str(),1);
      JsonDocument online; online["node_id"]=MTOS_NODE_ID; online["boot_id"]=bootId; online["availability"]="online"; publishJson("/availability",online,true); publishStatus();
    }
  }
}
void setup() {
  Serial.begin(115200); bootId=String((uint32_t)esp_random(),HEX)+String((uint32_t)esp_random(),HEX);
  pinMode(MTOS_SHIFT_DATA_PIN,OUTPUT); pinMode(MTOS_SHIFT_CLOCK_PIN,OUTPUT); pinMode(MTOS_SHIFT_LATCH_PIN,OUTPUT); pinMode(MTOS_SHIFT_OE_PIN,OUTPUT); digitalWrite(MTOS_SHIFT_OE_PIN,HIGH);
  pinMode(MTOS_MACHINE_RELAY_PIN,OUTPUT); digitalWrite(MTOS_MACHINE_RELAY_PIN,LOW);
  Wire.begin(); pwm.begin(); pwm.setPWMFreq(50); for(int i=0;i<16;i++) pwm.setPWM(i,0,4096);
  positions.begin("mtos-turnout",false);
  shiftImage=0; for(auto &s:SIGNALS) shiftImage|=s.stopMask; shiftLatch(); digitalWrite(MTOS_SHIFT_OE_PIN,LOW);
  WiFi.mode(WIFI_STA); mqtt.setServer(MTOS_MQTT_HOST,MTOS_MQTT_PORT); mqtt.setCallback(mqttMessage);
}
void loop() {
  serialCommissioning(); connectNetwork(); mqtt.loop(); uint32_t now=millis();
  static uint32_t lastStatus=0,lastFlash=0; if(now-lastStatus>5000){lastStatus=now;if(mqtt.connected())publishStatus();}
  if(now-lastFlash>500){lastFlash=now;shiftImage^=BUFFER_MASK;shiftLatch();}
  if(runner==SERVO_SWEEP){ if((int32_t)(deadline-now)<=0){finish("failed","execution_timeout");return;} int delta=servoTarget-servoStep; if(abs(delta)<=3){servoStep=servoTarget;pwm.setPWM(servoCurrent,0,servoStep);runner=SERVO_SETTLE;deadline=now+250;} else {servoStep+=delta>0?3:-3;pwm.setPWM(servoCurrent,0,servoStep);} }
  else if(runner==SERVO_SETTLE && (int32_t)(now-deadline)>=0){pwm.setPWM(servoCurrent,0,4096);servoIndex++;if(servoIndex<activeTurnout->count){String prior=positions.getString(activeAsset.c_str(),"");servoCurrent=activeTurnout->servo[servoIndex].channel;servoStep=prior=="straight"?activeTurnout->servo[servoIndex].straight:activeTurnout->servo[servoIndex].diverging;servoTarget=targetValue=="straight"?activeTurnout->servo[servoIndex].straight:activeTurnout->servo[servoIndex].diverging;runner=SERVO_SWEEP;deadline=now+2500;}else{positions.putString(activeAsset.c_str(),targetValue);finish("completed");}}
  else if(runner==SIGNAL_BREAK && (int32_t)(now-deadline)>=0){shiftImage|=targetValue=="stop"?activeSignal->stopMask:targetValue=="slow"?activeSignal->slowMask:activeSignal->goMask;shiftLatch();finish("completed");}
  else if(runner==MACHINE_CONTACT && (int32_t)(now-deadline)>=0){digitalWrite(MTOS_MACHINE_RELAY_PIN,LOW);runner=MACHINE_WAIT;deadline=now+WATER_TANK_CYCLE_MS;}
  else if(runner==MACHINE_WAIT && (int32_t)(now-deadline)>=0)finish("completed");
}
