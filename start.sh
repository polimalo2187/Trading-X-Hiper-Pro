#!/bin/bash

echo "🚀 Iniciando Trading X Hiper Pro..."

# Activar webhook o polling según configuración
if [ "$USE_WEBHOOK" = "true" ]; then
    echo "📡 Ejecutando en modo WEBHOOK"
    python3 main.py webhook
else
    echo "🎯 Ejecutando en modo POLLING"
    python3 main.py
fi
