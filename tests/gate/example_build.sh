#!/bin/sh
# Сборка одного примера в нативный бинарник (make build_all_examples).
# Параллельный воркер xargs -P.
set -eu
env $EATC build $RT "$1"
