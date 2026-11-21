#!/usr/bin/env bash

# This script is used to flash a patched AT25SF321 image
# with a Tigard tool in SPI mode

set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <patched_image.bin>" >&2
  exit 1
fi

IMAGE="$1"
PROG="ft2232_spi:type=2232H,port=B,divisor=4"

LAYOUT=$(mktemp /tmp/at25sf321b.XXXXXX.layout)
trap 'rm -f "$LAYOUT"' EXIT

cat << 'EOF' > "$LAYOUT"
0x000000:0x000fff sector0
0x200000:0x200fff sector512
EOF

sudo flashrom -p "$PROG" -c "AT25SF321" \
  -l "$LAYOUT" -i sector0 -i sector512 \
  -w "$IMAGE"
