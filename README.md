<img src="assets/logo.png" width="420"/>

# 🚀 Trading X Hiper Pro  
Bot profesional de trading automático para **HyperLiquid PERP**, construido en Python y totalmente integrado con Telegram.

Este sistema ejecuta operaciones reales 24/7 usando la estrategia **BlackCrow Aggressive**, con análisis dinámico del mercado, cálculo inteligente de TP/SL y gestión de riesgo de nivel institucional.

Incluye módulo de referidos, fees automáticos, panel de control vía Telegram y motor de trading avanzado.

---

## 🔥 Características principales

### ✅ Trading automático 24/7  
El bot analiza el mercado en tiempo real y ejecuta operaciones únicamente en pares PERP con **USDC**.

### 🎯 Estrategia BlackCrow Aggressive  
- Señal basada en volatilidad + microtendencia  
- Take Profit dinámico  
- Stop Loss proporcional  
- Señales reales, no simuladas

### ⚙ Gestión de riesgo profesional  
- Capital mínimo: **5 USDC**  
- Tamaño de posición 100% automático  
- Control de riesgo inteligente  
- Manejo de errores y reconexión automática

### 💼 Sistema de referidos  
- 5% del fee generado por cada usuario invitado  
- 15% del profit diario reservado al Administrador  
- Pagos semanales y diarios automatizados

### 👑 Panel del Administrador  
- Dashboard completo vía Telegram  
- Log de ganancias diarias  
- Resumen de operaciones  
- Control total del motor del bot

---

## 📦 Estructura del proyecto

```
Trading-X-Hiper-Pro/
│
├── main.py
├── start.sh
├── runtime.txt
├── requirements.txt
├── Procfile
│
├── assets/
│   └── logo.png
│
└── app/
    ├── bot.py
    ├── config.py
    ├── database.py
    ├── hyperliquid_client.py
    ├── log_config.py
    ├── market_scanner.py
    ├── risk.py
    ├── strategy.py
    ├── trading_engine.py
    └── trading_loop.py
```

---

## ⚙ Instalación

```bash
pip install -r requirements.txt
```

Configura las variables en tu entorno:

```
BOT_TOKEN=xxxx
MONGO_URL=xxxx
```

---

## ▶ Ejecución

Modo Polling:

```bash
python3 main.py
```

Deploy en Railway / Render / Heroku usando:

```
start.sh
Procfile
runtime.txt
```

---

## 🛡 Advertencia  
Este bot ejecuta **trading real**.  
Asegúrate de probarlo en cuenta demo antes de usar capital real.

---

## 📩 Soporte  
Para asistencia o instalación, contacta al Administrador.
