"""Constants for Klyqa Local."""

DOMAIN = "klyqa_local"

CLOUD_HOST = "https://app-api.prod.qconnex.io"

CONF_UNIT_ID = "unit_id"
CONF_AES_KEY = "aes_key"
CONF_PRODUCT_ID = "product_id"

UDP_PORT = 2222
TCP_PORT = 3333

SCAN_INTERVAL_SECONDS = 30
REQUEST_TIMEOUT = 10
SYN_RETRY_SECONDS = 3
# polls that may fail in a row before the light is marked unavailable
MAX_POLL_FAILURES = 3
