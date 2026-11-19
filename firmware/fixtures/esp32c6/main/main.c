#include "cJSON.h"
#include "driver/usb_serial_jtag.h"
#include "esp_random.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "host/ble_hs.h"
#include "host/util/util.h"
#include "nimble/nimble_port.h"
#include "nimble/nimble_port_freertos.h"
#include "nvs_flash.h"
#include "services/gap/ble_svc_gap.h"
#include "services/gatt/ble_svc_gatt.h"
#include <assert.h>
#include <ctype.h>
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>

#define FIXTURE_NAME "BLEWright-C6"
#define MAX_VALUE 512
static const ble_uuid16_t service_uuid = BLE_UUID16_INIT(0xfff0);
static const ble_uuid16_t characteristic_uuid = BLE_UUID16_INIT(0xfff1);
static uint8_t value[MAX_VALUE] = {'B', 'L', 'E'};
static uint16_t value_length = 3;
static uint16_t value_handle;
static uint8_t manufacturer[6] = {0xff, 0xff};
static uint8_t own_type;
static char address_text[18];
static char nonce_hex[9];
static SemaphoreHandle_t usb_tx_lock;
static _Atomic bool synced, advertising, connected;
static _Atomic uint32_t reads, writes, subscriptions, notify_requests;
static int gap_event(struct ble_gap_event *event, void *arg);

static int access_value(uint16_t conn_handle, uint16_t attr_handle,
                        struct ble_gatt_access_ctxt *ctxt, void *arg) {
  if (ctxt->op == BLE_GATT_ACCESS_OP_READ_CHR) {
    reads++;
    return os_mbuf_append(ctxt->om, value, value_length) == 0
               ? 0
               : BLE_ATT_ERR_INSUFFICIENT_RES;
  }
  if (ctxt->op == BLE_GATT_ACCESS_OP_WRITE_CHR) {
    uint16_t length = OS_MBUF_PKTLEN(ctxt->om);
    if (length > MAX_VALUE)
      return BLE_ATT_ERR_INVALID_ATTR_VALUE_LEN;
    if (os_mbuf_copydata(ctxt->om, 0, length, value) != 0)
      return BLE_ATT_ERR_UNLIKELY;
    value_length = length;
    writes++;
    // NimBLE emits notifications only to subscribed centrals. The value is read
    // through access_value when the pending notification is serialized.
    ble_gatts_chr_updated(value_handle);
    notify_requests++;
    return 0;
  }
  return BLE_ATT_ERR_UNLIKELY;
}

static const struct ble_gatt_svc_def services[] = {
    {.type = BLE_GATT_SVC_TYPE_PRIMARY,
     .uuid = &service_uuid.u,
     .characteristics =
         (struct ble_gatt_chr_def[]){
             {.uuid = &characteristic_uuid.u,
              .access_cb = access_value,
              .flags = BLE_GATT_CHR_F_READ | BLE_GATT_CHR_F_WRITE |
                       BLE_GATT_CHR_F_WRITE_NO_RSP | BLE_GATT_CHR_F_NOTIFY,
              .val_handle = &value_handle},
             {0}}},
    {0}};

static void advertise(void) {
  struct ble_hs_adv_fields fields = {0};
  fields.flags = BLE_HS_ADV_F_DISC_GEN | BLE_HS_ADV_F_BREDR_UNSUP;
  fields.uuids16 = (ble_uuid16_t *)&service_uuid;
  fields.num_uuids16 = 1;
  fields.uuids16_is_complete = 1;
  fields.name = (const uint8_t *)FIXTURE_NAME;
  fields.name_len = strlen(FIXTURE_NAME);
  fields.name_is_complete = 1;
  fields.mfg_data = manufacturer;
  fields.mfg_data_len = sizeof(manufacturer);
  // Legacy advertisement: flags 3 + UUID16 4 + name 14 + manufacturer 8 = 29.
  int rc = ble_gap_adv_set_fields(&fields);
  assert(rc == 0);
  struct ble_gap_adv_params params = {0};
  params.conn_mode = BLE_GAP_CONN_MODE_UND;
  params.disc_mode = BLE_GAP_DISC_MODE_GEN;
  rc = ble_gap_adv_start(own_type, NULL, BLE_HS_FOREVER, &params, gap_event,
                         NULL);
  advertising = rc == 0;
}

static int gap_event(struct ble_gap_event *event, void *arg) {
  switch (event->type) {
  case BLE_GAP_EVENT_CONNECT:
    connected = event->connect.status == 0;
    advertising = false;
    if (!connected)
      advertise();
    break;
  case BLE_GAP_EVENT_DISCONNECT:
    connected = false;
    advertise();
    break;
  case BLE_GAP_EVENT_ADV_COMPLETE:
    advertising = false;
    if (!connected)
      advertise();
    break;
  case BLE_GAP_EVENT_SUBSCRIBE:
    if (event->subscribe.attr_handle == value_handle &&
        event->subscribe.cur_notify) {
      subscriptions++;
      ble_gatts_chr_updated(value_handle);
      notify_requests++;
    }
    break;
  default:
    break;
  }
  return 0;
}

static void sync_host(void) {
  int rc = ble_hs_util_ensure_addr(0);
  assert(rc == 0);
  rc = ble_hs_id_infer_auto(0, &own_type);
  assert(rc == 0);
  uint8_t address[6];
  rc = ble_hs_id_copy_addr(own_type, address, NULL);
  assert(rc == 0);
  snprintf(address_text, sizeof(address_text), "%02X:%02X:%02X:%02X:%02X:%02X",
           address[5], address[4], address[3], address[2], address[1],
           address[0]);
  synced = true;
  advertise();
}

static void reset_host(int reason) {
  synced = false;
  advertising = false;
  connected = false;
}
static void host_task(void *arg) {
  nimble_port_run();
  nimble_port_freertos_deinit();
}

static void send_identity(const char *request_id) {
  if (!synced)
    return;
  cJSON *o = cJSON_CreateObject();
  cJSON_AddStringToObject(o, "type", "fixtureIdentity");
  cJSON_AddStringToObject(o, "firmware", "blewright-c6-fixture/0.2");
  if (request_id)
    cJSON_AddStringToObject(o, "requestId", request_id);
  cJSON_AddStringToObject(o, "chip", "ESP32-C6");
  cJSON_AddStringToObject(o, "name", FIXTURE_NAME);
  cJSON_AddStringToObject(o, "address", address_text);
  cJSON_AddNumberToObject(o, "addressType", own_type);
  cJSON_AddStringToObject(o, "nonce", nonce_hex);
  cJSON_AddNumberToObject(o, "manufacturerId", 65535);
  cJSON_AddBoolToObject(o, "advertising", advertising);
  cJSON_AddBoolToObject(o, "connected", connected);
  cJSON_AddNumberToObject(o, "reads", reads);
  cJSON_AddNumberToObject(o, "writes", writes);
  cJSON_AddNumberToObject(o, "subscriptions", subscriptions);
  cJSON_AddNumberToObject(o, "notifyRequests", notify_requests);
  char *json = cJSON_PrintUnformatted(o);
  cJSON_Delete(o);
  if (json) {
    xSemaphoreTake(usb_tx_lock, portMAX_DELAY);
    usb_serial_jtag_write_bytes(json, strlen(json), pdMS_TO_TICKS(100));
    usb_serial_jtag_write_bytes("\n", 1, pdMS_TO_TICKS(100));
    xSemaphoreGive(usb_tx_lock);
    free(json);
  }
}
static void usb_identity_task(void *arg) {
  for (;;) {
    send_identity(NULL);
    vTaskDelay(pdMS_TO_TICKS(1000));
  }
}
static void usb_query_task(void *arg) {
  char line[256];
  size_t used = 0;
  bool overflow = false;
  for (;;) {
    uint8_t ch;
    if (usb_serial_jtag_read_bytes(&ch, 1, pdMS_TO_TICKS(100)) != 1)
      continue;
    if (ch != '\n') {
      if (used < sizeof(line) - 1 && !overflow)
        line[used++] = ch;
      else
        overflow = true;
      continue;
    }
    line[used] = 0;
    if (!overflow) {
      cJSON *q = cJSON_Parse(line);
      const cJSON *op = cJSON_GetObjectItemCaseSensitive(q, "op");
      const cJSON *id = cJSON_GetObjectItemCaseSensitive(q, "requestId");
      bool valid = cJSON_IsString(op) && !strcmp(op->valuestring, "identity") &&
                   cJSON_IsString(id) && strlen(id->valuestring) == 32;
      if (valid)
        for (int i = 0; i < 32; i++)
          if (!isxdigit((unsigned char)id->valuestring[i]))
            valid = false;
      if (valid) {
        // Read-only: no BLE state mutation is exposed over USB. Echo the fresh
        // request ID so old boot announcements can never authorize a
        // connection.
        for (int i = 0; i < 100 && !synced; i++)
          vTaskDelay(pdMS_TO_TICKS(20));
        send_identity(id->valuestring);
      }
      cJSON_Delete(q);
    }
    used = 0;
    overflow = false;
  }
}

void app_main(void) {
  esp_fill_random(manufacturer + 2, 4);
  snprintf(nonce_hex, sizeof(nonce_hex), "%02X%02X%02X%02X", manufacturer[2],
           manufacturer[3], manufacturer[4], manufacturer[5]);
  usb_serial_jtag_driver_config_t usb = {.tx_buffer_size = 4096,
                                         .rx_buffer_size = 256};
  ESP_ERROR_CHECK(usb_serial_jtag_driver_install(&usb));
  usb_tx_lock = xSemaphoreCreateMutex();
  assert(usb_tx_lock);
  // Never erase NVS on error; original flash was backed up before provisioning.
  ESP_ERROR_CHECK(nvs_flash_init());
  ESP_ERROR_CHECK(nimble_port_init());
  ble_hs_cfg.sync_cb = sync_host;
  ble_hs_cfg.reset_cb = reset_host;
  ble_svc_gap_init();
  ble_svc_gatt_init();
  ble_svc_gap_device_name_set(FIXTURE_NAME);
  assert(ble_gatts_count_cfg(services) == 0);
  assert(ble_gatts_add_svcs(services) == 0);
  nimble_port_freertos_init(host_task);
  xTaskCreate(usb_identity_task, "fixture_identity", 4096, NULL, 4, NULL);
  xTaskCreate(usb_query_task, "fixture_query", 4096, NULL, 4, NULL);
}
