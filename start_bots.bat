@echo off
echo Starting SyncInk Bots...

:: Start the Python main bot in a new window
start "SyncInk Python Bot" cmd /k "python ""SyncInk discord bot(beta)(1).py"""

:: Start the Node.js Ticket System
echo Starting Node.js Ticket System...
cd ticket-system
node src/index.js
pause
