#!/bin/sh

python3 - <<'EOF'
import socket, sys
try:
    s = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("::", 4499))
    s.listen(1)

    test = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        test.connect(("127.0.0.1", 4499))
        sys.exit(0)
    except Exception:
        sys.exit(1)
    finally:
        test.close()
except Exception:
    sys.exit(1)
finally:
    s.close()
EOF

if [ $? -eq 0 ]; then
    echo "Use IPv4-mapped IPv6"
    exec gunicorn -w 4 -b [::]:4499 turnify:app \
        --log-level "$(echo $LOG_LEVEL | tr '[:upper:]' '[:lower:]')" \
        --access-logfile "${GUNICORN_ACCESS_LOG:--}" \
        --error-logfile "${GUNICORN_ERROR_LOG:--}"
else
    echo "Use manual IPv4 and IPv6 binding"
    exec gunicorn -w 4 -b 0.0.0.0:4499 -b [::]:4499 turnify:app \
        --log-level "$(echo $LOG_LEVEL | tr '[:upper:]' '[:lower:]')" \
        --access-logfile "${GUNICORN_ACCESS_LOG:--}" \
        --error-logfile "${GUNICORN_ERROR_LOG:--}"
fi