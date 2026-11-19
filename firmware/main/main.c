#include "cJSON.h"
#include "driver/usb_serial_jtag.h"
#include "esp_log.h"
#include "esp_random.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "host/ble_hs.h"
#include "host/util/util.h"
#include "nimble/nimble_port.h"
#include "nimble/nimble_port_freertos.h"
#include "nvs_flash.h"
#include "wire.h"
#include <inttypes.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

// All BLE state and commands live on NimBLE's host event queue. USB RX/TX never
// accesses connection state; callbacks carry their original generation.
static QueueHandle_t tx_queue;
static SemaphoreHandle_t command_slots;
static char boot_id[17];
static _Atomic uint32_t tx_dropped;
static uint32_t generation, last_id, connecting_id, disconnect_id;
static uint16_t connection = BLE_HS_CONN_HANDLE_NONE;
static uint8_t own_address_type;
static bool ready, scanning, connecting;
static uint32_t scan_id;
static int64_t last_command_us;
static struct ble_npl_event lease_event;
typedef struct {
  uint32_t id, generation;
  const char *op;
} operation_t;
static operation_t *active;
typedef struct {
  struct ble_npl_event event;
  char *payload;
} command_t;

static cJSON *object(void) { return cJSON_CreateObject(); }
static cJSON *bytes_json(const uint8_t *p, size_t n) {
  cJSON *a = cJSON_CreateArray();
  for (size_t i = 0; i < n; i++)
    cJSON_AddItemToArray(a, cJSON_CreateNumber(p[i]));
  return a;
}
static void send_json(cJSON *message) {
  cJSON_AddStringToObject(message, "bootId", boot_id);
  cJSON_AddNumberToObject(message, "v", 1);
  char *json = cJSON_PrintUnformatted(message);
  cJSON_Delete(message);
  if (!json)
    return;
  char *frame = malloc(BW_FRAME_SIZE);
  int n = frame ? bw_frame(frame, BW_FRAME_SIZE, json, strlen(json)) : -1;
  free(json);
  if (n < 0 || xQueueSend(tx_queue, &frame, 0) != pdTRUE) {
    free(frame);
    tx_dropped++;
  }
}
static cJSON *result(uint32_t id, int status) {
  cJSON *o = object();
  cJSON_AddStringToObject(o, "type", "result");
  cJSON_AddNumberToObject(o, "id", id);
  cJSON_AddNumberToObject(o, "status", status);
  cJSON_AddNumberToObject(o, "generation", generation);
  return o;
}
static void respond(uint32_t id, int status) { send_json(result(id, status)); }
static void reject(uint32_t id, const char *code) {
  cJSON *o = result(id, -1);
  cJSON_AddStringToObject(o, "error", code);
  send_json(o);
}
static cJSON *event(const char *name) {
  cJSON *o = object();
  cJSON_AddStringToObject(o, "type", "event");
  cJSON_AddStringToObject(o, "event", name);
  cJSON_AddNumberToObject(o, "generation", generation);
  return o;
}
static double number(cJSON *o, const char *key, double fallback) {
  cJSON *v = cJSON_GetObjectItemCaseSensitive(o, key);
  return cJSON_IsNumber(v) ? v->valuedouble : fallback;
}
static const char *string(cJSON *o, const char *key) {
  cJSON *v = cJSON_GetObjectItemCaseSensitive(o, key);
  return cJSON_IsString(v) ? v->valuestring : "";
}
static void uuid_json(cJSON *o, const ble_uuid_t *uuid) {
  char text[BLE_UUID_STR_LEN];
  ble_uuid_to_str(uuid, text);
  cJSON_AddStringToObject(o, "uuid", text);
}
static void address_text(const ble_addr_t *a, char out[18]) {
  snprintf(out, 18, "%02X:%02X:%02X:%02X:%02X:%02X", a->val[5], a->val[4],
           a->val[3], a->val[2], a->val[1], a->val[0]);
}
static operation_t *begin(uint32_t id, const char *op) {
  if (active) {
    reject(id, "BUSY");
    return NULL;
  }
  operation_t *p = calloc(1, sizeof(*p));
  if (!p) {
    reject(id, "NO_MEMORY");
    return NULL;
  }
  p->id = id;
  p->generation = generation;
  p->op = op;
  active = p;
  return p;
}
static void finish(operation_t *p, int status, cJSON *extra) {
  if (p->generation == generation) {
    cJSON *o = result(p->id, status);
    if (extra)
      cJSON_AddItemToObject(o, "data", extra);
    send_json(o);
  } else
    cJSON_Delete(extra);
  if (active == p)
    active = NULL;
  free(p);
}
static int attr_callback(uint16_t conn, const struct ble_gatt_error *error,
                         struct ble_gatt_attr *attr, void *arg) {
  operation_t *p = arg;
  cJSON *data = NULL;
  if (error->status == 0 && attr && attr->om) {
    uint8_t value[512];
    uint16_t len = OS_MBUF_PKTLEN(attr->om);
    if (len > sizeof(value)) {
      finish(p, BLE_HS_EMSGSIZE, NULL);
      return 0;
    }
    os_mbuf_copydata(attr->om, 0, len, value);
    data = object();
    cJSON_AddNumberToObject(data, "handle", attr->handle);
    cJSON_AddItemToObject(data, "value", bytes_json(value, len));
  }
  finish(p, error->status, data);
  return 0;
}
static int service_callback(uint16_t conn, const struct ble_gatt_error *error,
                            const struct ble_gatt_svc *svc, void *arg) {
  operation_t *p = arg;
  if (error->status) {
    finish(p, error->status == BLE_HS_EDONE ? 0 : error->status, NULL);
    return 0;
  }
  if (p->generation == generation) {
    cJSON *o = event("service");
    cJSON_AddNumberToObject(o, "id", p->id);
    cJSON_AddNumberToObject(o, "start", svc->start_handle);
    cJSON_AddNumberToObject(o, "end", svc->end_handle);
    uuid_json(o, &svc->uuid.u);
    send_json(o);
  }
  return 0;
}
static int characteristic_callback(uint16_t conn,
                                   const struct ble_gatt_error *error,
                                   const struct ble_gatt_chr *chr, void *arg) {
  operation_t *p = arg;
  if (error->status) {
    finish(p, error->status == BLE_HS_EDONE ? 0 : error->status, NULL);
    return 0;
  }
  if (p->generation == generation) {
    cJSON *o = event("characteristic");
    cJSON_AddNumberToObject(o, "id", p->id);
    cJSON_AddNumberToObject(o, "definitionHandle", chr->def_handle);
    cJSON_AddNumberToObject(o, "handle", chr->val_handle);
    cJSON_AddNumberToObject(o, "properties", chr->properties);
    uuid_json(o, &chr->uuid.u);
    send_json(o);
  }
  return 0;
}
static int descriptor_callback(uint16_t conn,
                               const struct ble_gatt_error *error, uint16_t chr,
                               const struct ble_gatt_dsc *dsc, void *arg) {
  operation_t *p = arg;
  if (error->status) {
    finish(p, error->status == BLE_HS_EDONE ? 0 : error->status, NULL);
    return 0;
  }
  if (p->generation == generation) {
    cJSON *o = event("descriptor");
    cJSON_AddNumberToObject(o, "id", p->id);
    cJSON_AddNumberToObject(o, "characteristicHandle", chr);
    cJSON_AddNumberToObject(o, "handle", dsc->handle);
    uuid_json(o, &dsc->uuid.u);
    send_json(o);
  }
  return 0;
}
static int mtu_callback(uint16_t conn, const struct ble_gatt_error *error,
                        uint16_t mtu, void *arg) {
  cJSON *data = object();
  cJSON_AddNumberToObject(data, "mtu", mtu);
  finish(arg, error->status, data);
  return 0;
}
static int gap_callback(struct ble_gap_event *e, void *arg) {
  switch (e->type) {
  case BLE_GAP_EVENT_DISC:
    if (scanning) {
      char addr[18];
      address_text(&e->disc.addr, addr);
      cJSON *o = event("advertisement");
      cJSON_AddNumberToObject(o, "scanId", scan_id);
      cJSON_AddStringToObject(o, "address", addr);
      cJSON_AddNumberToObject(o, "addressType", e->disc.addr.type);
      cJSON_AddNumberToObject(o, "rssi", e->disc.rssi);
      cJSON_AddNumberToObject(o, "eventType", e->disc.event_type);
      cJSON_AddItemToObject(o, "advertising",
                            bytes_json(e->disc.data, e->disc.length_data));
      send_json(o);
    }
    break;
  case BLE_GAP_EVENT_DISC_COMPLETE:
    if (scanning) {
      scanning = false;
      cJSON *o = event("scanStopped");
      cJSON_AddNumberToObject(o, "scanId", scan_id);
      cJSON_AddNumberToObject(o, "reason", e->disc_complete.reason);
      send_json(o);
    }
    break;
  case BLE_GAP_EVENT_CONNECT: {
    uint32_t id = connecting_id;
    connecting = false;
    connecting_id = 0;
    if (e->connect.status == 0) {
      connection = e->connect.conn_handle;
      generation++;
    }
    cJSON *o = result(id, e->connect.status);
    cJSON_AddNumberToObject(o, "mtu",
                            e->connect.status ? 0 : ble_att_mtu(connection));
    send_json(o);
    break;
  }
  case BLE_GAP_EVENT_DISCONNECT: {
    connection = BLE_HS_CONN_HANDLE_NONE;
    generation++;
    cJSON *o = event("disconnected");
    cJSON_AddNumberToObject(o, "reason", e->disconnect.reason);
    send_json(o);
    if (disconnect_id) {
      respond(disconnect_id, 0);
      disconnect_id = 0;
    }
    break;
  }
  case BLE_GAP_EVENT_NOTIFY_RX: {
    uint8_t value[512];
    uint16_t len = OS_MBUF_PKTLEN(e->notify_rx.om);
    if (len > sizeof(value))
      break;
    os_mbuf_copydata(e->notify_rx.om, 0, len, value);
    cJSON *o = event("notification");
    cJSON_AddNumberToObject(o, "handle", e->notify_rx.attr_handle);
    cJSON_AddBoolToObject(o, "indication", e->notify_rx.indication);
    cJSON_AddItemToObject(o, "value", bytes_json(value, len));
    send_json(o);
    break;
  }
  default:
    break;
  }
  return 0;
}
static void execute(cJSON *q) {
  double raw_id = number(q, "id", 0);
  if (raw_id < 1 || raw_id > UINT32_MAX || raw_id != (uint32_t)raw_id) {
    reject(0, "INVALID_ID");
    return;
  }
  uint32_t id = (uint32_t)raw_id;
  const char *op = string(q, "op");
  cJSON *p = cJSON_GetObjectItemCaseSensitive(q, "params");
  if (number(q, "v", 0) != 1 || id == 0) {
    reject(id, "INVALID_ENVELOPE");
    return;
  }
  if (!strcmp(op, "hello")) {
    last_command_us = esp_timer_get_time();
    cJSON *o = result(id, 0);
    cJSON_AddStringToObject(o, "firmware", "blewright-s3/0.2");
    cJSON_AddBoolToObject(o, "ready", ready);
    cJSON_AddBoolToObject(o, "connected",
                          connection != BLE_HS_CONN_HANDLE_NONE);
    cJSON_AddBoolToObject(o, "connecting", connecting);
    cJSON_AddBoolToObject(o, "scanning", scanning);
    cJSON_AddBoolToObject(o, "passiveScanSupported", true);
    cJSON_AddNumberToObject(o, "maxPayload", BW_MAX_PAYLOAD);
    cJSON_AddNumberToObject(o, "droppedFrames", tx_dropped);
    cJSON_AddNumberToObject(o, "lastId", last_id);
    cJSON_AddStringToObject(o, "capabilities",
                            "scan,connect,cancel,disconnect,services,"
                            "characteristics,descriptors,read,write,mtu,rssi");
    send_json(o);
    return;
  }
  if (strcmp(string(q, "bootId"), boot_id)) {
    reject(id, "BOOT_ID_MISMATCH");
    return;
  }
  if (id <= last_id) {
    reject(id, "REPLAY");
    return;
  }
  last_id = id;
  last_command_us = esp_timer_get_time();
  if (!strcmp(op, "ping")) {
    respond(id, 0);
    return;
  }
  if (!ready) {
    reject(id, "NOT_READY");
    return;
  }
  if (!strcmp(op, "scan.start")) {
    if (scanning || connecting) {
      reject(id, "BUSY");
      return;
    }
    cJSON *passive = cJSON_GetObjectItemCaseSensitive(p, "passive");
    if (passive && !cJSON_IsBool(passive)) {
      reject(id, "INVALID_ARGUMENT");
      return;
    }
    struct ble_gap_disc_params config = {0};
    // Omitted means active for backwards compatibility; true sends no scan
    // requests.
    config.passive = cJSON_IsTrue(passive) ? 1 : 0;
    config.itvl = 0x30;
    config.window = 0x30;
    config.filter_duplicates = 1;
    scan_id = id;
    int rc = ble_gap_disc(own_address_type, 10000, &config, gap_callback, NULL);
    scanning = rc == 0;
    cJSON *o = result(id, rc);
    cJSON_AddBoolToObject(o, "passive", config.passive != 0);
    send_json(o);
    return;
  }
  if (!strcmp(op, "scan.stop")) {
    int rc = scanning ? ble_gap_disc_cancel() : 0;
    scanning = false;
    respond(id, rc);
    return;
  }
  if (!strcmp(op, "connect")) {
    if (connection != BLE_HS_CONN_HANDLE_NONE || connecting || active) {
      reject(id, "BUSY");
      return;
    }
    unsigned b[6];
    double raw_type = number(p, "addressType", 0);
    if ((raw_type != 0 && raw_type != 1) ||
        strlen(string(p, "address")) != 17) {
      reject(id, "INVALID_ADDRESS");
      return;
    }
    ble_addr_t address = {.type = (uint8_t)raw_type};
    if (address.type > 1 ||
        sscanf(string(p, "address"), "%2x:%2x:%2x:%2x:%2x:%2x", &b[5], &b[4],
               &b[3], &b[2], &b[1], &b[0]) != 6) {
      reject(id, "INVALID_ADDRESS");
      return;
    }
    for (int i = 0; i < 6; i++)
      address.val[i] = b[i];
    if (scanning) {
      ble_gap_disc_cancel();
      scanning = false;
    }
    connecting = true;
    connecting_id = id;
    int rc = ble_gap_connect(own_address_type, &address, 10000, NULL,
                             gap_callback, NULL);
    if (rc) {
      connecting = false;
      connecting_id = 0;
      respond(id, rc);
    }
    return;
  }
  if (!strcmp(op, "cancel")) {
    int rc = connecting ? ble_gap_conn_cancel() : 0;
    respond(id, rc);
    return;
  }
  if (connection == BLE_HS_CONN_HANDLE_NONE) {
    reject(id, "NOT_CONNECTED");
    return;
  }
  if (number(q, "generation", -1) != generation) {
    reject(id, "STALE_GENERATION");
    return;
  }
  if (!strcmp(op, "disconnect")) {
    if (disconnect_id) {
      reject(id, "BUSY");
      return;
    }
    disconnect_id = id;
    int rc = ble_gap_terminate(connection, BLE_ERR_REM_USER_CONN_TERM);
    if (rc) {
      disconnect_id = 0;
      respond(id, rc);
    }
    return;
  }
  if (!strcmp(op, "rssi")) {
    int8_t rssi;
    int rc = ble_gap_conn_rssi(connection, &rssi);
    cJSON *o = result(id, rc);
    cJSON_AddNumberToObject(o, "rssi", rc ? 0 : rssi);
    send_json(o);
    return;
  }
  if (strcmp(op, "services") && strcmp(op, "characteristics") &&
      strcmp(op, "descriptors") && strcmp(op, "read") && strcmp(op, "write") &&
      strcmp(op, "mtu")) {
    reject(id, "UNSUPPORTED");
    return;
  }
  double raw_start = number(p, "start", 1), raw_end = number(p, "end", 65535),
         raw_handle = number(p, "handle", 0);
  if (raw_start < 1 || raw_start > 65535 || raw_end < 1 || raw_end > 65535 ||
      raw_handle < 0 || raw_handle > 65535 ||
      raw_start != (uint16_t)raw_start || raw_end != (uint16_t)raw_end ||
      raw_handle != (uint16_t)raw_handle) {
    reject(id, "INVALID_RANGE");
    return;
  }
  uint16_t start = (uint16_t)number(p, "start", 1),
           end = (uint16_t)number(p, "end", 65535),
           handle = (uint16_t)number(p, "handle", 0);
  if (start == 0 || end < start) {
    reject(id, "INVALID_RANGE");
    return;
  }
  uint8_t value[512];
  int length = 0;
  if (!strcmp(op, "read") || !strcmp(op, "write")) {
    if (!handle) {
      reject(id, "INVALID_HANDLE");
      return;
    }
  }
  if (!strcmp(op, "write")) {
    cJSON *a = cJSON_GetObjectItemCaseSensitive(p, "value");
    length = cJSON_GetArraySize(a);
    if (!cJSON_IsArray(a) || length > ble_att_mtu(connection) - 3 ||
        length > 512) {
      reject(id, "INVALID_LENGTH");
      return;
    }
    for (int i = 0; i < length; i++) {
      cJSON *v = cJSON_GetArrayItem(a, i);
      if (!cJSON_IsNumber(v) || v->valuedouble < 0 || v->valuedouble > 255 ||
          v->valuedouble != (int)v->valuedouble) {
        reject(id, "INVALID_VALUE");
        return;
      }
      value[i] = v->valueint;
    }
  }
  operation_t *pending = begin(id, !strcmp(op, "read") ? "read" : "operation");
  if (!pending)
    return;
  int rc;
  if (!strcmp(op, "services"))
    rc = ble_gattc_disc_all_svcs(connection, service_callback, pending);
  else if (!strcmp(op, "characteristics"))
    rc = ble_gattc_disc_all_chrs(connection, start, end,
                                 characteristic_callback, pending);
  else if (!strcmp(op, "descriptors"))
    rc = ble_gattc_disc_all_dscs(connection, start, end, descriptor_callback,
                                 pending);
  else if (!strcmp(op, "read"))
    rc = ble_gattc_read(connection, handle, attr_callback, pending);
  else if (!strcmp(op, "mtu"))
    rc = ble_gattc_exchange_mtu(connection, mtu_callback, pending);
  else if (cJSON_IsTrue(
               cJSON_GetObjectItemCaseSensitive(p, "withoutResponse"))) {
    rc = ble_gattc_write_no_rsp_flat(connection, handle, value, length);
    finish(pending, rc, NULL);
    return;
  } else
    rc = ble_gattc_write_flat(connection, handle, value, length, attr_callback,
                              pending);
  if (rc)
    finish(pending, rc, NULL);
}
static void command_event(struct ble_npl_event *event) {
  command_t *cmd = ble_npl_event_get_arg(event);
  cJSON *q = cJSON_Parse(cmd->payload);
  if (q) {
    execute(q);
    cJSON_Delete(q);
  } else
    reject(0, "INVALID_JSON");
  free(cmd->payload);
  ble_npl_event_deinit(&cmd->event);
  free(cmd);
  xSemaphoreGive(command_slots);
}
static void tx_task(void *arg) {
  char *frame;
  for (;;) {
    if (xQueueReceive(tx_queue, &frame, portMAX_DELAY) == pdTRUE) {
      size_t length = strlen(frame), offset = 0;
      while (offset < length) {
        int n = usb_serial_jtag_write_bytes(frame + offset, length - offset,
                                            pdMS_TO_TICKS(100));
        if (n <= 0) {
          tx_dropped++;
          break;
        }
        offset += n;
      }
      free(frame);
    }
  }
}
static void rx_task(void *arg) {
  char line[BW_FRAME_SIZE];
  size_t used = 0;
  bool overflow = false;
  for (;;) {
    uint8_t ch;
    if (usb_serial_jtag_read_bytes(&ch, 1, pdMS_TO_TICKS(50)) != 1)
      continue;
    if (ch == '\n') {
      if (!overflow) {
        line[used++] = '\n';
        const char *payload;
        size_t length;
        if (!bw_unframe(line, used, &payload, &length) &&
            xSemaphoreTake(command_slots, 0) == pdTRUE) {
          command_t *cmd = calloc(1, sizeof(*cmd));
          if (cmd) {
            cmd->payload = malloc(length + 1);
            if (cmd->payload) {
              memcpy(cmd->payload, payload, length);
              cmd->payload[length] = 0;
              ble_npl_event_init(&cmd->event, command_event, cmd);
              ble_npl_eventq_put(nimble_port_get_dflt_eventq(), &cmd->event);
            } else {
              free(cmd);
              xSemaphoreGive(command_slots);
            }
          } else
            xSemaphoreGive(command_slots);
        }
      }
      used = 0;
      overflow = false;
    } else if (used < sizeof(line) - 2 && !overflow)
      line[used++] = ch;
    else
      overflow = true;
  }
}
static void lease_callback(struct ble_npl_event *event_arg) {
  if (last_command_us && esp_timer_get_time() - last_command_us > 15000000 &&
      (scanning || connecting || connection != BLE_HS_CONN_HANDLE_NONE)) {
    if (scanning) {
      scanning = false;
      ble_gap_disc_cancel();
    }
    if (connecting)
      ble_gap_conn_cancel();
    if (connection != BLE_HS_CONN_HANDLE_NONE)
      ble_gap_terminate(connection, BLE_ERR_REM_USER_CONN_TERM);
    send_json(event("leaseExpired"));
    last_command_us = 0;
  }
}
static void lease_task(void *arg) {
  for (;;) {
    vTaskDelay(pdMS_TO_TICKS(1000));
    ble_npl_eventq_put(nimble_port_get_dflt_eventq(), &lease_event);
  }
}
static void sync_callback(void) {
  int rc = ble_hs_util_ensure_addr(0);
  if (!rc)
    rc = ble_hs_id_infer_auto(0, &own_address_type);
  ready = rc == 0;
}
static void reset_callback(int reason) {
  ready = false;
  connection = BLE_HS_CONN_HANDLE_NONE;
  generation++;
  cJSON *o = event("hostReset");
  cJSON_AddNumberToObject(o, "reason", reason);
  send_json(o);
}
static void host_task(void *arg) {
  nimble_port_run();
  nimble_port_freertos_deinit();
}
void app_main(void) {
  snprintf(boot_id, sizeof(boot_id), "%08" PRIx32 "%08" PRIx32, esp_random(),
           esp_random());
  tx_queue = xQueueCreate(64, sizeof(char *));
  command_slots = xSemaphoreCreateCounting(8, 8);
  assert(tx_queue && command_slots);
  usb_serial_jtag_driver_config_t usb = {.tx_buffer_size = 4096,
                                         .rx_buffer_size = 4096};
  ESP_ERROR_CHECK(usb_serial_jtag_driver_install(&usb));
  // Do not erase existing NVS automatically: preserve user state on errors.
  ESP_ERROR_CHECK(nvs_flash_init());
  ESP_ERROR_CHECK(nimble_port_init());
  ble_hs_cfg.sync_cb = sync_callback;
  ble_hs_cfg.reset_cb = reset_callback;
  ble_npl_event_init(&lease_event, lease_callback, NULL);
  nimble_port_freertos_init(host_task);
  xTaskCreate(tx_task, "bw_tx", 4096, NULL, 5, NULL);
  xTaskCreate(rx_task, "bw_rx", 6144, NULL, 5, NULL);
  xTaskCreate(lease_task, "bw_lease", 2048, NULL, 4, NULL);
}
