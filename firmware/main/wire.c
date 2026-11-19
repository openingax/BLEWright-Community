#include "wire.h"
#include <stdio.h>
#include <string.h>
uint32_t bw_crc32(const void *data, size_t length) {
  const uint8_t *p = data;
  uint32_t crc = 0xffffffff;
  for (size_t i = 0; i < length; i++) {
    crc ^= p[i];
    for (int bit = 0; bit < 8; bit++)
      crc = (crc >> 1) ^ ((crc & 1) ? 0xedb88320 : 0);
  }
  return crc ^ 0xffffffff;
}
int bw_frame(char *out, size_t capacity, const char *json, size_t length) {
  if (length > BW_MAX_PAYLOAD || capacity < length + BW_HEADER_SIZE + 2)
    return -1;
  int n = snprintf(out, capacity, "@BW1 %04X %08X ", (unsigned)length,
                   (unsigned)bw_crc32(json, length));
  if (n != BW_HEADER_SIZE)
    return -1;
  memcpy(out + n, json, length);
  out[n + length] = '\n';
  out[n + length + 1] = 0;
  return n + length + 1;
}
int bw_unframe(const char *line, size_t length, const char **payload,
               size_t *payload_length) {
  unsigned size, crc;
  if (length < BW_HEADER_SIZE + 1 || memcmp(line, "@BW1 ", 5) ||
      line[9] != ' ' || line[18] != ' ' || line[length - 1] != '\n')
    return -1;
  if (sscanf(line + 5, "%4x %8x", &size, &crc) != 2 || size > BW_MAX_PAYLOAD ||
      length != size + BW_HEADER_SIZE + 1)
    return -1;
  if (bw_crc32(line + BW_HEADER_SIZE, size) != crc)
    return -1;
  *payload = line + BW_HEADER_SIZE;
  *payload_length = size;
  return 0;
}
