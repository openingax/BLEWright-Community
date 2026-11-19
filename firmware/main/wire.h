#pragma once
#include <stddef.h>
#include <stdint.h>
#define BW_MAX_PAYLOAD 3072
#define BW_HEADER_SIZE 19
#define BW_FRAME_SIZE (BW_MAX_PAYLOAD + BW_HEADER_SIZE + 2)
uint32_t bw_crc32(const void *data, size_t length);
int bw_frame(char *out, size_t capacity, const char *json, size_t length);
int bw_unframe(const char *line, size_t length, const char **payload,
               size_t *payload_length);
