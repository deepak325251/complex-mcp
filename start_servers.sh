#!/bin/zsh

# Signal handler function
cleanup() {
    echo -e "\nReceived interrupt signal, shutting down all child processes..."
    
    # Send SIGTERM to all child processes
    for PID in "${PIDS[@]}"; do
        if kill -0 $PID 2>/dev/null; then
            echo "Shutting down process $PID"
            kill $PID
        fi
    done
    
    # Wait for all processes to finish
    wait
    echo "All processes have been terminated"
    exit 0
}

# Set up signal traps
trap cleanup INT TERM

# Array to store process IDs
PIDS=()

echo "Starting Local MCP suite..."

# Start each servers
fastmcp run servers/math/app.py --transport http --host 0.0.0.0 --port 8000 &
PIDS+=($!)
sleep 1

python -m servers.unit.app --host 0.0.0.0 --port 8001 &
PIDS+=($!)
echo "Started UnitServer ..."
sleep 1

fastmcp run servers/osint/app.py --transport http --host 0.0.0.0 --port 8002 &
PIDS+=($!)
sleep 1

fastmcp run servers/time/app.py --transport http --host 0.0.0.0 --port 8003 &
PIDS+=($!)
sleep 1

fastmcp run servers/lang/app.py --transport http --host 0.0.0.0 --port 8004 &
PIDS+=($!)
sleep 1

fastmcp run servers/crypto/app.py --transport http --host 0.0.0.0 --port 8005 &
PIDS+=($!)
sleep 1

fastmcp run servers/graphs/app.py --transport http --host 0.0.0.0 --port 8006 &
PIDS+=($!)
sleep 1

fastmcp run servers/chem/app.py --transport http --host 0.0.0.0 --port 8007 &
PIDS+=($!)
sleep 1

fastmcp run servers/url/app.py --transport http --host 0.0.0.0 --port 8013 &
PIDS+=($!)
echo "Started URLServer ..."
sleep 1

fastmcp run servers/csv_server/app.py --transport http --host 0.0.0.0 --port 8014 &
PIDS+=($!)
echo "Started CSVServer ..."
sleep 1

fastmcp run servers/json_server/app.py --transport http --host 0.0.0.0 --port 8015 &
PIDS+=($!)
echo "Started JSONServer ..."
sleep 1

fastmcp run servers/diff/app.py --transport http --host 0.0.0.0 --port 8016 &
PIDS+=($!)
echo "Started DiffServer ..."
sleep 1

fastmcp run servers/hash/app.py --transport http --host 0.0.0.0 --port 8017 &
PIDS+=($!)
echo "Started HashServer ..."
sleep 1

fastmcp run servers/color/app.py --transport http --host 0.0.0.0 --port 8018 &
PIDS+=($!)
echo "Started ColorServer ..."
sleep 1

fastmcp run servers/encoding/app.py --transport http --host 0.0.0.0 --port 8019 &
PIDS+=($!)
echo "Started EncodingServer ..."
sleep 1

fastmcp run servers/barcode/app.py --transport http --host 0.0.0.0 --port 8020 &
PIDS+=($!)
echo "Started BarcodeServer ..."
sleep 1

fastmcp run servers/calendar_math/app.py --transport http --host 0.0.0.0 --port 8021 &
PIDS+=($!)
echo "Started CalendarMathServer ..."
sleep 1

fastmcp run servers/currency/app.py --transport http --host 0.0.0.0 --port 8022 &
PIDS+=($!)
echo "Started CurrencyServer ..."
sleep 1

fastmcp run servers/random_server/app.py --transport http --host 0.0.0.0 --port 8023 &
PIDS+=($!)
echo "Started RandomServer ..."
sleep 1

fastmcp run servers/template/app.py --transport http --host 0.0.0.0 --port 8024 &
PIDS+=($!)
echo "Started TemplateServer ..."
sleep 1

echo "All MCP servers started successfully. Press Ctrl+C to shut down all servers."

# Wait for all processes
for PID in "${PIDS[@]}"; do
    wait $PID
done
