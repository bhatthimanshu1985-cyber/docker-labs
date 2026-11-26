#!/bin/sh
# Start the push loop only if PRTG push target is configured
if [ -n "$PRTG_PUSH_URL" ]; then
  push.sh &
fi
exec docker-php-entrypoint "$@"
