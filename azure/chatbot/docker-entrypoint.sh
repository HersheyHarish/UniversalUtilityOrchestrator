#!/bin/sh
set -e
# Refresh deps when package.json changes (anonymous /app/node_modules volume can go stale)
npm install
exec npm run dev -- --host 0.0.0.0
