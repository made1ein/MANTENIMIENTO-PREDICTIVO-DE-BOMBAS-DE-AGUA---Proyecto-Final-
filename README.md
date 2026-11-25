# MANTENIMIENTO-PREDICTIVO-DE-BOMBAS-DE-AGUA---Proyecto-Final-
# Mantenimiento predictivo de bombas de agua

Raspberry Pi Pico 2 W programada en MicroPython con Thonny.
Componentes: ADXL345, INA219, DS18B20, módulo de relé y bomba de 12 V DC.

Archivos que se copian a la Pico:

- sensores.py: drivers de los tres sensores.
- main.py: programa principal (calibración, índice de salud, tendencia, relé y comandos).

Archivos que crea el programa dentro de la Pico:

- linea_base.json: valores de la bomba sana.
- registro.csv: historial de mediciones para el informe.


## 1. Conexiones

| Componente | Pin del módulo | Va a |
|---|---|---|
| ADXL345 | VCC | 3V3(OUT), pin 36 de la Pico |
| ADXL345 | GND | GND |
| ADXL345 | SDA | GP4, pin 6 |
| ADXL345 | SCL | GP5, pin 7 |
| ADXL345 | CS | 3V3 (activa el modo I2C) |
| ADXL345 | SDO | GND (dirección 0x53) |
| ADXL345 | INT1 | GP14, pin 19 (aviso de vibración fuerte, ver sección 10) |
| INA219 | VCC | 3V3(OUT) |
| INA219 | GND | GND |
| INA219 | SDA | GP4 (mismo bus que el ADXL345) |
| INA219 | SCL | GP5 (mismo bus que el ADXL345) |
| INA219 | VIN+ | + de la fuente de 12 V |
| INA219 | VIN- | COM del relé |
| Relé | VCC | VBUS, pin 40 (5 V del USB), si el módulo es de 5 V |
| Relé | GND | GND |
| Relé | IN | GP15, pin 20 |
| Relé | NO | + de la bomba |
| Bomba | - | GND de la fuente de 12 V |
| DS18B20 | rojo | 3V3(OUT) |
| DS18B20 | negro | GND |
| DS18B20 | amarillo (datos) | GP16, pin 21 |

Notas:

- La tierra de la fuente de 12 V debe unirse con la tierra de la Pico. Sin esa unión, el INA219 no mide bien.
- El ADXL345 se conecta por I2C y no por SPI, como dice la imagen referencial. Así comparte los dos cables del bus con el INA219 y el código es más corto. Es el mismo módulo.
- El DS18B20 necesita una resistencia de 4.7 kΩ entre el cable de datos y 3V3. El código activa la resistencia interna de la Pico, que a veces basta con cable corto, pero no es confiable. Si el programa dice "DS18B20 no encontrado", falta esa resistencia.
- El ADXL345 va fijo a la carcasa de la bomba, en el soporte impreso. El DS18B20 va pegado al cuerpo del motor, no metido en el agua.
- Si el relé se activa al revés (la bomba prende cuando debería estar apagada), cambiar RELE_ACTIVO_EN_ALTO a False en main.py.
- El cable INT1 del ADXL345 a GP14 solo se usa para el reto de la sección 10. Sin ese cable el resto del sistema funciona igual, pero la parada por interrupción no se activa.


## 2. Puesta en marcha en Thonny

1. Instalar MicroPython en la Pico: Tools > Options > Interpreter, elegir "MicroPython (Raspberry Pi Pico)" y luego "Install or update MicroPython", variante Pico 2 W.
2. Abrir sensores.py y main.py en Thonny. En cada uno: File > Save as > Raspberry Pi Pico, con el mismo nombre.
3. Ejecutar main.py con el botón verde.
4. La primera vez calibra durante 2 minutos. La bomba debe estar sana, con agua y sin nada que la obstruya.
5. Abrir View > Plotter para ver las curvas.

Al llamarse main.py, el programa también arranca solo cuando la Pico se alimenta sin PC. En ese caso el LED integrado indica el estado.

Recomendación: antes de la primera calibración, dejar la bomba funcionando unos 10 minutos para que el motor llegue a su temperatura normal de trabajo. Si se calibra con el motor frío, el calentamiento normal puede leerse como falla.


## 3. Qué se ve en el Plotter

En modo gráfico se dibujan cuatro curvas y dos líneas de referencia:

- vib, corr, temp: cuántas desviaciones estándar se aleja cada variable de la bomba sana (puntaje z).
- salud: el peor de los tres puntajes. Es el índice de salud.
- alerta (3) y critico (6): umbrales fijos, para ver cuándo se cruzan.

Se grafican puntajes z y no valores reales porque las variables tienen escalas muy distintas: unos 30 °C frente a unos 0.05 g. En puntaje z todas oscilan alrededor de 0.


## 4. Comandos (se escriben en la consola de Thonny y se pulsa Enter)

| Letra | Acción |
|---|---|
| c | Recalibrar la línea base (2 minutos) |
| r | Rearmar: volver a encender la bomba tras un estado crítico o una parada manual |
| p | Parada manual de la bomba |
| m | Cambiar entre modo gráfico (Plotter) y modo datos (valores reales con unidades y tiempo estimado a falla) |
| s | Resumen: estado, índice, valores frente a la línea base, pendiente y tiempo estimado a falla |
| h | Ayuda |


## 5. LED integrado de la Pico

| LED | Significado |
|---|---|
| Encendido fijo | Normal |
| Parpadeo lento | Alerta: programar mantenimiento |
| Parpadeo rápido | Crítico: bomba detenida, esperando el comando r |
| Apagado | Parada manual |


## 6. Cómo decide el sistema

1. Cada segundo se toman 200 muestras del acelerómetro y se calcula la vibración RMS sin la gravedad. Además se promedian 10 lecturas de corriente y se lee la temperatura.
2. Cada variable se compara con la bomba sana: z = (valor - media de la línea base) / desviación de la línea base.
3. El índice de salud es el peor |z|. La temperatura solo cuenta cuando sube, porque un motor más frío no indica falla.
4. Estados: índice menor que 3, normal; entre 3 y 6, alerta; 6 o más, o temperatura de 60 °C o más, crítico, y el relé detiene la bomba.
5. Un cambio de estado se acepta solo si se repite en 3 lecturas seguidas. Así un golpe aislado no detiene la bomba.
6. Parte predictiva: con los últimos 60 valores del índice se ajusta una recta por mínimos cuadrados. Si la pendiente es positiva, se estima cuánto falta para llegar a 6: tiempo = (6 - índice actual) / pendiente.
7. El estado crítico queda enclavado: la bomba no vuelve a arrancar sola aunque las lecturas mejoren.

Si un sensor deja de responder durante la marcha, el programa se detiene y la bomba se apaga.


## 7. Fallas para simular en la demostración

- Marcha en seco: sacar la manguera de entrada del agua. La corriente baja y la temperatura empieza a subir.
- Obstrucción: pinzar la manguera de salida. Cambian la corriente y la vibración.
- Montaje flojo: aflojar los tornillos del soporte de la bomba. Sube la vibración.
- Degradación progresiva: pinzar la manguera de salida poco a poco durante uno o dos minutos. Es la mejor prueba de la parte predictiva, porque se ve cómo el tiempo estimado a falla disminuye antes de llegar al estado crítico.


## 8. Ajustes (sección 1 de main.py)

- Z_ALERTA y Z_CRITICO: umbrales del índice de salud.
- DESV_MIN: desviación mínima por variable. Si salta la alerta con cambios que a simple vista no significan nada, subir el valor de esa variable.
- T_CALIBRACION_S: duración de la calibración.
- PERIODO_MS y N_MUESTRAS_VIB: ritmo de medición. El periodo no debe bajar de 800 ms, porque el DS18B20 tarda unos 750 ms en cada lectura.


## 9. Descargar los datos para el informe

En Thonny: View > Files. En el panel de la Pico, clic derecho sobre registro.csv > Download. Se abre en Excel. Cada fila es una medición cada 5 segundos, con un tope de 5000 filas. Para empezar un registro nuevo, borrar registro.csv desde el mismo panel.


## 10. Reto de arquitectura: parada de emergencia por interrupción

Hasta ahora el programa revisa el estado por sondeo (polling): mide una vez por segundo y solo corta la bomba cuando el estado crítico se repite N_CONFIRMAR veces seguidas. Eso protege contra falsas alarmas, pero una vibración violenta tarda varios segundos en detener la bomba.

El reto reemplaza ese sondeo, en el caso de una vibración extrema, por una interrupción de hardware:

1. El ADXL345 vigila la aceleración por sí solo. Está configurado en modo de actividad, acoplado en AC (ignora la gravedad) y en los tres ejes.
2. Cuando la aceleración cambia más que UMBRAL_EMERGENCIA_G, el sensor levanta su pin INT1.
3. La Pico detecta ese flanco ascendente en GP14 y ejecuta la rutina de interrupción, que abre el relé de inmediato. La rutina hace lo mínimo: abrir el relé y levantar una bandera.
4. El ciclo principal ve la bandera, pasa el estado a CRÍTICO, apaga el LED de estado normal y escribe el aviso en la consola.

La interrupción convive con el índice de salud: el índice sigue gestionando los estados normal, alerta y crítico, y la interrupción actúa solo como parada de emergencia con un umbral alto.

Cuándo está activa:

- Se arma recién pasados ESPERA_ARRANQUE_S segundos del arranque, para que el golpe de encendido de la bomba no la dispare.
- Se desarma durante la calibración, tras un estado crítico y con la parada manual.
- El comando r la vuelve a armar después del arranque.

### Ajustes del reto (sección 1 de main.py)

| Constante | Valor | Qué hace |
|---|---|---|
| USAR_INTERRUPCION | True | False deja solo el sondeo, para medir el "antes" |
| PIN_INT1 | 14 | Pin de la Pico conectado a INT1 del ADXL345 |
| UMBRAL_EMERGENCIA_G | 3.0 | Cambio de aceleración, en g, que corta la bomba al instante |

El ADXL345 trabaja en rango de ±4 g, así que el umbral debe quedar dentro de ese rango. Si la bomba se corta sola funcionando normal, subir el umbral. Si no corta con un golpe seco y fuerte, bajarlo. Debe quedar por encima de la vibración normal de la bomba.

### Qué se ve en la consola

Parada por interrupción:

```
>>> EMERGENCIA por interrupcion (vibracion > 3.0 g): rele abierto en XX us
    bomba detenida. Revisar y escribir r para rearmar
```

Parada por sondeo (índice crítico confirmado):

```
>>> CRITICO por vibracion: bomba detenida. Revisar y escribir r para rearmar
    latencia de parada por sondeo: X.X s desde la primera lectura critica
```

### Cómo probarlo

1. Con INT1 conectado a GP14 y USAR_INTERRUPCION = True, ejecutar main.py y esperar unos 5 segundos.
2. Dar un golpe seco al soporte del acelerómetro. El relé debe hacer clic y la bomba detenerse al instante.
3. Escribir r para rearmar.
4. Para el "antes": poner USAR_INTERRUPCION = False, repetir una vibración fuerte y anotar la latencia por sondeo.

### Resultados antes y después

| Modo | Latencia de parada |
|---|---|
| Sondeo (USAR_INTERRUPCION = False) | [completar, en segundos] |
| Interrupción (USAR_INTERRUPCION = True) | [completar, en microsegundos] más el periodo de muestreo del sensor (unos 0.6 ms a 1600 Hz) |


## 11. Nube: Ubidots

El programa envía los datos a Ubidots por HTTPS (método POST) al dispositivo de etiqueta `bomba`, cada 5 mediciones, es decir, cada 5 segundos aproximadamente.

| Variable | Contenido | Unidad |
|---|---|---|
| vib | Vibración RMS | g |
| corr | Corriente | A |
| volt | Voltaje de la bomba | V |
| temp | Temperatura del motor | °C |
| salud | Índice de salud | z |

Configuración al inicio de main.py:

- WIFI_SSID y WIFI_PASS: red Wi-Fi a la que se conecta la Pico.
- UBIDOTS_TOKEN: token de la cuenta de Ubidots.
- DEVICE_LABEL: etiqueta del dispositivo en Ubidots.

No subir al repositorio el token ni la contraseña reales. Si se publicaron por error, regenerar el token en Ubidots y cambiar la contraseña del Wi-Fi.

Dashboard: [agregar captura con las gráficas de vibración, corriente, temperatura e índice de salud].

Alerta: [agregar captura de la alerta configurada en Ubidots y del aviso recibido].


## 12. Limitaciones conocidas

- Al arrancar, el programa espera a conectarse al Wi-Fi y no inicia hasta lograrlo.
- El envío a Ubidots es bloqueante: si la red falla, el ciclo de medición puede detenerse hasta que la petición termine o falle.
- El umbral de la interrupción es fijo y se ajusta a mano según el montaje del sensor y la bomba.
- La línea base proviene de una sola calibración con una sola bomba.
