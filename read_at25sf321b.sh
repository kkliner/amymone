#!/usr/bin/env bash

# This script is used to read the contents of an AT25SF321
# with a Tigard tool in SPI mode

set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <output_image.bin>" >&2
  exit 1
fi

IMAGE="$1"
PROG="ft2232_spi:type=2232H,port=B,divisor=4"

if [[ -e "$IMAGE" ]]; then
  echo "Error: '$IMAGE' already exists. Refusing to overwrite." >&2
  exit 1
fi

sudo flashrom -p "$PROG" -c "AT25SF321" -r "$IMAGE"
