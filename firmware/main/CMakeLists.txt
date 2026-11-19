idf_component_register(SRCS "main.c" "wire.c" INCLUDE_DIRS "." REQUIRES bt nvs_flash esp_driver_usb_serial_jtag json esp_timer)
