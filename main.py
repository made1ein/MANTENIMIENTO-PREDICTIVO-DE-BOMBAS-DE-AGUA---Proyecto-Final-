# ============================================================
#  main.py
#  Mantenimiento predictivo de una bomba de agua de 12 V
#  Raspberry Pi Pico 2 W + ADXL345 + INA219 + DS18B20 + relé
#
#  Uso:
#   1. Copiar sensores.py y main.py a la Pico desde Thonny.
#   2. Ejecutar main.py. La primera vez calibra la bomba sana.
#   3. Ver las curvas en Thonny: menú View > Plotter.
#   4. Escribir comandos en la consola de Thonny (h = ayuda).
# ============================================================

import sys
import time
import json
import select
from machine import Pin, I2C, Timer
from sensores import ADXL345, INA219, DS18B20
import network
import urequests
import ujson

WIFI_SSID = "Alee"
WIFI_PASS = "pibblefeliz"
UBIDOTS_TOKEN = "BBUS-AHwGkkluvH0QJHdkT3gczvSw2Coobn"
DEVICE_LABEL = "bomba"

# Conectar al WiFi al arrancar
wlan = network.WLAN(network.STA_IF)
wlan.active(True)
wlan.connect(WIFI_SSID, WIFI_PASS)
print("Conectando a WiFi...")
while not wlan.isconnected():
    time.sleep(0.5)
time.sleep(3)  # Pausa después de conectar para asegurar DNS
print("WiFi conectado:", wlan.ifconfig()[0])

def enviar_ubidots(vib, corr, volt, temp, salud):
    url = "https://industrial.api.ubidots.com/api/v1.6/devices/" + DEVICE_LABEL
    headers = {"X-Auth-Token": UBIDOTS_TOKEN, "Content-Type": "application/json"}
    payload = ujson.dumps({
        "vib": round(vib, 4),
        "corr": round(corr, 3),
        "volt": round(volt, 2),
        "temp": round(temp, 2),
        "salud": round(salud, 2)
    })
    try:
        res = urequests.post(url, data=payload, headers=headers)
        print("Ubidots OK:", res.status_code)
        res.close()
    except Exception as e:
        print("Error Ubidots:", e)
# ------------------------------------------------------------
# 1. CONFIGURACIÓN (todo lo ajustable está aquí)
# ------------------------------------------------------------
PIN_SDA = 4              # I2C0 SDA -> ADXL345 e INA219
PIN_SCL = 5              # I2C0 SCL -> ADXL345 e INA219
PIN_DS18B20 = 16         # cable de datos del sensor de temperatura
PIN_RELE = 15            # entrada IN del módulo de relé
RELE_ACTIVO_EN_ALTO = True   # poner False si el relé se activa con 0

# [RETO] Interrupción por vibración excesiva
USAR_INTERRUPCION = True     # False = solo sondeo (sirve para medir el "antes")
PIN_INT1 = 14                # pin INT1 del ADXL345 -> GP14
UMBRAL_EMERGENCIA_G = 3.0    # cambio de aceleración que corta la bomba al instante

PERIODO_MS = 1000        # una medición por segundo
N_MUESTRAS_VIB = 200     # muestras del acelerómetro en cada medición
T_CALIBRACION_S = 120    # duración de la calibración
ESPERA_ARRANQUE_S = 3    # se ignora el pico de corriente al arrancar

Z_ALERTA = 15.0           # índice de salud que activa la ALERTA
Z_CRITICO = 30.0          # índice de salud que detiene la bomba
TEMP_MAX_C = 75.0        # límite absoluto de temperatura del motor
N_CONFIRMAR = 8          # lecturas seguidas para aceptar un cambio de estado

# Desviación mínima de cada variable. Evita que una línea base
# demasiado "quieta" dispare alarmas con cambios insignificantes.
DESV_MIN = {"vib": 0.05, "corr": 0.15, "temp": 3.0}

VENTANA_TENDENCIA = 60   # puntos usados para la recta (60 s)
PENDIENTE_MIN = 0.005    # pendiente mínima (z por segundo) para tomarla en serio

ARCHIVO_BASE = "linea_base.json"
ARCHIVO_CSV = "registro.csv"
GUARDAR_CADA = 5         # se guarda 1 de cada 5 mediciones
MAX_LINEAS_CSV = 5000    # tope para no llenar la memoria flash

# ------------------------------------------------------------
# 2. HARDWARE
# ------------------------------------------------------------
rele = Pin(PIN_RELE, Pin.OUT)


def bomba(encender):
    """Enciende o apaga la bomba a través del relé."""
    rele.value(1 if encender == RELE_ACTIVO_EN_ALTO else 0)


bomba(False)             # por seguridad, todo arranca con la bomba apagada

led = Pin("LED", Pin.OUT)                 # LED integrado de la Pico
i2c = I2C(0, sda=Pin(PIN_SDA), scl=Pin(PIN_SCL), freq=400000)
acel = ADXL345(i2c)
ina = INA219(i2c)
termo = DS18B20(Pin(PIN_DS18B20, Pin.PULL_UP))

# ------------------------------------------------------------
# 2b. [RETO] INTERRUPCIÓN DE EMERGENCIA
# En vez de esperar a la próxima medición (sondeo), el ADXL345 avisa
# por su pin INT1 apenas la vibración pasa del umbral, y la Pico abre
# el relé dentro de la rutina de interrupción, en microsegundos.
# La rutina hace lo mínimo (abrir el relé y levantar una bandera);
# lo demás (estado, mensajes) lo hace el programa principal.
# ------------------------------------------------------------
RELE_APAGADO = 0 if RELE_ACTIVO_EN_ALTO else 1
armada = False           # la interrupción solo actúa con la bomba ya estabilizada
emergencia = False       # la rutina de interrupción la pone en True
dur_isr_us = 0           # microsegundos que tardó la rutina en abrir el relé


def isr_emergencia(pin):
    """Se ejecuta apenas el ADXL345 levanta INT1."""
    global emergencia, dur_isr_us
    if not armada:
        return
    t0 = time.ticks_us()
    rele.value(RELE_APAGADO)                          # corta la bomba ya
    dur_isr_us = time.ticks_diff(time.ticks_us(), t0)
    emergencia = True


def armar_interrupcion():
    """Borra avisos viejos (como el golpe del arranque) y activa la parada."""
    global armada
    acel.limpiar_interrupcion()
    armada = True


def desarmar_interrupcion():
    global armada
    armada = False


def atender_emergencia():
    """Ya se abrió el relé en la interrupción: aquí solo se actualiza el estado."""
    global emergencia, armada, estado
    emergencia = False
    armada = False
    acel.limpiar_interrupcion()
    estado = CRITICO
    print(">>> EMERGENCIA por interrupcion (vibracion > {:.1f} g): rele abierto en {} us".format(
        UMBRAL_EMERGENCIA_G, dur_isr_us))
    print("    bomba detenida. Revisar y escribir r para rearmar")


pin_int = Pin(PIN_INT1, Pin.IN, Pin.PULL_DOWN)
if USAR_INTERRUPCION:
    acel.configurar_actividad(UMBRAL_EMERGENCIA_G)
    pin_int.irq(trigger=Pin.IRQ_RISING, handler=isr_emergencia)
else:
    acel.desactivar_interrupcion()

# ------------------------------------------------------------
# 3. ESTADO DEL SISTEMA
# ------------------------------------------------------------
NORMAL, ALERTA, CRITICO = 0, 1, 2
NOMBRE = ("NORMAL", "ALERTA", "CRITICO")

estado = NORMAL
parada_manual = False
modo_grafico = True      # True: z-scores para el Plotter. False: valores reales
t_arranque = 0           # momento en que se encendió la bomba
candidato = NORMAL       # estado que se está confirmando
cuenta = 0               # cuántas lecturas seguidas lleva el candidato
t_critico = [0]          # [RETO] instante de la primera lectura crítica (para medir la latencia por sondeo)

# El LED integrado muestra el estado aunque no haya PC conectada:
#   fijo = normal | parpadeo lento = alerta | parpadeo rápido = crítico
#   apagado = bomba detenida a mano
_tic = 0


def actualizar_led(_):
    global _tic
    _tic += 1
    if parada_manual:
        led.off()
    elif estado == NORMAL:
        led.on()
    elif estado == ALERTA:
        led.value((_tic // 2) % 2)
    else:
        led.value(_tic % 2)


timer_led = Timer(period=250, mode=Timer.PERIODIC, callback=actualizar_led)

# ------------------------------------------------------------
# 4. MEDICIÓN
# ------------------------------------------------------------
def medir():
    """Devuelve vibración RMS [g], corriente [A], voltaje [V] y temperatura [°C]."""
    vib = acel.vibracion_rms(N_MUESTRAS_VIB)
    suma = 0.0
    for _ in range(10):                  # promedio de 10 lecturas de corriente
        suma += ina.corriente()
        time.sleep_ms(1)
    corr = abs(suma / 10)
    volt = ina.voltaje()
    temp = termo.leer()                  # conversión iniciada en la vuelta anterior
    termo.iniciar_conversion()           # estará lista en la próxima vuelta
    return vib, corr, volt, temp


def esperar_periodo(t_inicio):
    """Completa el periodo para que cada vuelta dure PERIODO_MS."""
    restante = PERIODO_MS - time.ticks_diff(time.ticks_ms(), t_inicio)
    if restante > 0:
        time.sleep_ms(restante)

# ------------------------------------------------------------
# 5. CALIBRACIÓN: línea base de la bomba sana
# ------------------------------------------------------------
def calibrar():
    print(">>> CALIBRACION: la bomba debe estar sana, con agua y sin obstrucciones")
    desarmar_interrupcion()              # [RETO] durante la calibración no se corta la bomba
    bomba(True)
    time.sleep(ESPERA_ARRANQUE_S)
    datos = {"vib": [], "corr": [], "temp": []}
    n_total = T_CALIBRACION_S * 1000 // PERIODO_MS
    for i in range(n_total):
        t0 = time.ticks_ms()
        vib, corr, _, temp = medir()
        datos["vib"].append(vib)
        datos["corr"].append(corr)
        datos["temp"].append(temp)
        if (i + 1) % 10 == 0:
            print("    calibrando... {} de {} mediciones".format(i + 1, n_total))
        esperar_periodo(t0)

    base = {}
    for clave, valores in datos.items():
        media = sum(valores) / len(valores)
        desv = (sum((v - media) * 2 for v in valores) / len(valores)) * 0.5
        base[clave] = [media, max(desv, DESV_MIN[clave])]

    with open(ARCHIVO_BASE, "w") as f:
        json.dump(base, f)
    print(">>> Linea base guardada en " + ARCHIVO_BASE)
    print("    vibracion:   {:.4f} g  (desv. {:.4f})".format(base["vib"][0], base["vib"][1]))
    print("    corriente:   {:.3f} A  (desv. {:.3f})".format(base["corr"][0], base["corr"][1]))
    print("    temperatura: {:.1f} C  (desv. {:.1f})".format(base["temp"][0], base["temp"][1]))
    return base


def cargar_base():
    try:
        with open(ARCHIVO_BASE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None

# ------------------------------------------------------------
# 6. ÍNDICE DE SALUD
# ------------------------------------------------------------
def puntajes_z(base, vib, corr, temp):
    """Cuántas desviaciones estándar se aleja cada variable de la bomba sana."""
    zv = (vib - base["vib"][0]) / base["vib"][1]
    zc = (corr - base["corr"][0]) / base["corr"][1]
    zt = (temp - base["temp"][0]) / base["temp"][1]
    return zv, zc, zt


def indice_salud(zv, zc, zt):
    """El índice es la peor de las tres desviaciones.
    Vibración y corriente cuentan hacia arriba y hacia abajo
    (marcha en seco = menos corriente). La temperatura solo cuenta
    hacia arriba: un motor más frío no es una falla."""
    opciones = (("vibracion", abs(zv)), ("corriente", abs(zc)), ("temperatura", max(zt, 0)))
    causa, valor = max(opciones, key=lambda o: o[1])
    return valor, causa

# ------------------------------------------------------------
# 7. TENDENCIA: la parte predictiva
# ------------------------------------------------------------
hist_t = []
hist_s = []


def tendencia(t, salud):
    """Ajusta la recta  salud = a + m*t  a los últimos puntos
    por mínimos cuadrados y estima cuándo cruzará el umbral crítico.
    Devuelve (m, segundos hasta falla). Si hay pocos datos: (None, None).
    Si la salud no empeora: (m, None)."""
    hist_t.append(t)
    hist_s.append(salud)
    if len(hist_t) > VENTANA_TENDENCIA:
        hist_t.pop(0)
        hist_s.pop(0)
    n = len(hist_t)
    if n < VENTANA_TENDENCIA // 2:
        return None, None

    t_med = sum(hist_t) / n
    s_med = sum(hist_s) / n
    num = 0.0
    den = 0.0
    for ti, si in zip(hist_t, hist_s):
        num += (ti - t_med) * (si - s_med)
        den += (ti - t_med) ** 2
    m = num / den                          # pendiente: cuánto empeora por segundo
    s_ahora = s_med + m * (t - t_med)      # valor de la recta en este instante

    if m < PENDIENTE_MIN or s_ahora >= Z_CRITICO:
        return m, None
    return m, (Z_CRITICO - s_ahora) / m


def texto_falla(m, t_falla):
    if m is None:
        return "calculando"
    if t_falla is None:
        return "estable"
    return "{:.1f} min".format(t_falla / 60)

# ------------------------------------------------------------
# 8. REGISTRO EN CSV (memoria flash de la Pico)
# ------------------------------------------------------------
CABECERA = "t_s,vib_g,corr_A,volt_V,temp_C,z_vib,z_corr,z_temp,salud,estado,t_falla_s\n"


def contar_lineas():
    try:
        n = 0
        with open(ARCHIVO_CSV) as f:
            for _ in f:
                n += 1
        return n
    except OSError:
        with open(ARCHIVO_CSV, "w") as f:
            f.write(CABECERA)
        return 1


lineas_csv = contar_lineas()


def registrar(valores):
    global lineas_csv
    if lineas_csv >= MAX_LINEAS_CSV:
        return
    with open(ARCHIVO_CSV, "a") as f:
        f.write(",".join(valores) + "\n")
    lineas_csv += 1

# ------------------------------------------------------------
# 9. COMANDOS POR PUERTO SERIE (consola de Thonny)
# ------------------------------------------------------------
lector = select.poll()
lector.register(sys.stdin, select.POLLIN)


def leer_comandos():
    """Devuelve lo que se escribió en la consola, sin detener el programa."""
    letras = ""
    while lector.poll(0):
        letras += sys.stdin.read(1)
    return letras.lower()


def ayuda():
    print(">>> Comandos: c=calibrar  r=rearmar  p=parar  m=cambiar modo  s=resumen  h=ayuda")


def rearmar():
    """Vuelve a encender la bomba y reinicia la evaluación."""
    global estado, parada_manual, t_arranque, candidato, cuenta
    estado = NORMAL
    parada_manual = False
    candidato = NORMAL
    cuenta = 0
    del hist_t[:]
    del hist_s[:]
    desarmar_interrupcion()              # [RETO] se vuelve a armar pasado el arranque
    bomba(True)
    t_arranque = time.ticks_ms()


def cambiar_estado(nuevo, causa):
    global estado
    estado = nuevo
    if nuevo == CRITICO:
        bomba(False)
        desarmar_interrupcion()          # [RETO]
        print(">>> CRITICO por {}: bomba detenida. Revisar y escribir r para rearmar".format(causa))
        # [RETO] latencia del sondeo: de la primera lectura crítica al corte
        print("    latencia de parada por sondeo: {:.1f} s desde la primera lectura critica".format(
            time.ticks_diff(time.ticks_ms(), t_critico[0]) / 1000))
    elif nuevo == ALERTA:
        print(">>> ALERTA por {}: programar mantenimiento".format(causa))
    else:
        print(">>> Vuelta a estado NORMAL")


def resumen(base, vib, corr, temp, salud, causa, m, t_falla):
    print(">>> RESUMEN")
    print("    estado: {} | indice de salud: {:.1f} (mayor aporte: {})".format(
        "DETENIDA" if parada_manual else NOMBRE[estado], salud, causa))
    print("    vibracion {:.3f} g (base {:.3f}) | corriente {:.3f} A (base {:.3f}) | temperatura {:.1f} C (base {:.1f})".format(
        vib, base["vib"][0], corr, base["corr"][0], temp, base["temp"][0]))
    print("    pendiente: {} | tiempo estimado a falla: {}".format(
        "-" if m is None else "{:+.4f} z/s".format(m), texto_falla(m, t_falla)))
    print("    lineas en {}: {} de {}".format(ARCHIVO_CSV, lineas_csv, MAX_LINEAS_CSV))

# ------------------------------------------------------------
# 10. PROGRAMA PRINCIPAL
# ------------------------------------------------------------
def main():
    global modo_grafico, parada_manual, candidato, cuenta

    base = cargar_base()
    if base is None:
        base = calibrar()
    else:
        print(">>> Linea base cargada. Escribir c para recalibrar")
    ayuda()

    rearmar()
    t_cero = time.ticks_ms()
    m, t_falla = None, None
    vuelta = 0

    while True:
        t_vuelta = time.ticks_ms()

        # [RETO] si la interrupción ya abrió el relé, actualizar el estado
        if emergencia:
            atender_emergencia()

        # a) medir y calcular el índice de salud
        vib, corr, volt, temp = medir()
        t = time.ticks_diff(time.ticks_ms(), t_cero) / 1000
        zv, zc, zt = puntajes_z(base, vib, corr, temp)
        salud, causa = indice_salud(zv, zc, zt)

        funcionando = estado != CRITICO and not parada_manual
        en_arranque = time.ticks_diff(time.ticks_ms(), t_arranque) < ESPERA_ARRANQUE_S * 1000

        # [RETO] pasado el arranque, se arma la parada por interrupción
        if USAR_INTERRUPCION and funcionando and not en_arranque and not armada:
            armar_interrupcion()

        # b) decidir el estado (solo con la bomba en marcha y ya estabilizada)
        if funcionando and not en_arranque:
            if temp >= TEMP_MAX_C:
                nivel, causa = CRITICO, "temperatura"
            elif salud >= Z_CRITICO:
                nivel = CRITICO
            elif salud >= Z_ALERTA:
                nivel = ALERTA
            else:
                nivel = NORMAL

            # un cambio se acepta solo si se repite N_CONFIRMAR veces seguidas
            if nivel == candidato:
                cuenta += 1
            else:
                candidato, cuenta = nivel, 1
                if nivel == CRITICO:
                    t_critico[0] = time.ticks_ms()   # [RETO] inicio de la cuenta de latencia
            if cuenta >= N_CONFIRMAR and nivel != estado:
                cambiar_estado(nivel, causa)

            m, t_falla = tendencia(t, salud)

        # c) atender comandos del usuario
        for letra in leer_comandos():
            if letra == "c":
                base = calibrar()
                rearmar()
            elif letra == "r":
                rearmar()
                print(">>> Bomba rearmada")
            elif letra == "p":
                parada_manual = True
                bomba(False)
                desarmar_interrupcion()  # [RETO]
                print(">>> Parada manual. Escribir r para volver a arrancar")
            elif letra == "m":
                modo_grafico = not modo_grafico
            elif letra == "s":
                resumen(base, vib, corr, temp, salud, causa, m, t_falla)
            elif letra == "h":
                ayuda()

        # d) mostrar por el puerto serie
        if modo_grafico:
            if funcionando and not en_arranque:
                print("vib:{:.2f} corr:{:.2f} temp:{:.2f} salud:{:.2f} alerta:{:.0f} critico:{:.0f}".format(
                    zv, zc, zt, salud, Z_ALERTA, Z_CRITICO))
        else:
            print("t={:.0f}s  vib={:.3f}g  corr={:.3f}A  {:.1f}V  temp={:.1f}C  salud={:.1f}  {}  falla: {}".format(
                t, vib, corr, volt, temp, salud,
                "DETENIDA" if parada_manual else NOMBRE[estado],
                texto_falla(m, t_falla) if funcionando else "-"))

        # e) guardar en el CSV
        vuelta += 1
        if vuelta % GUARDAR_CADA == 0:
            registrar([
                "{:.1f}".format(t), "{:.4f}".format(vib), "{:.3f}".format(corr),
                "{:.2f}".format(volt), "{:.2f}".format(temp),
                "{:.2f}".format(zv), "{:.2f}".format(zc), "{:.2f}".format(zt),
                "{:.2f}".format(salud),
                "DETENIDA" if parada_manual else NOMBRE[estado],
                "" if t_falla is None else "{:.0f}".format(t_falla),
            ])
            enviar_ubidots(vib, corr, volt, temp, salud)

        esperar_periodo(t_vuelta)


try:
    main()
except KeyboardInterrupt:
    print(">>> Programa detenido por el usuario")
finally:
    bomba(False)                 # pase lo que pase, la bomba queda apagada
    timer_led.deinit()
    led.off()
    print(">>> Bomba apagada")
