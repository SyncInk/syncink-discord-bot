#!/bin/bash

echo "Starting Node.js Ticket System..."
cd ticket-system
npm install
node src/index.js &
NODE_PID=$!

echo "Starting Python SyncInk Bot..."
cd ..
python "SyncInk discord bot(beta)(1).py" &
PYTHON_PID=$!

# Wait for both processes
wait $NODE_PID
wait $PYTHON_PID
