# Punto de Venta de Escritorio

Aplicación de escritorio sencilla hecha con Tkinter para gestionar ventas con tickets en impresora térmica.

## Requisitos
- Python 3.11+
- tk incluido en la instalación de Python.
- Opcional: utilidades de impresión del sistema (`lpstat` y `lpr`) para enviar tickets a impresoras instaladas.

## Uso
1. Ejecuta la aplicación:
   ```bash
   python pos_app.py
   ```
2. **Importa productos** con el botón "Cargar productos CSV". El asistente permite mapear las columnas referencia, descripción, código de barras y precio antes de importar.
3. **Abre caja** con el botón "Abrir caja" para empezar a registrar ventas.
4. Selecciona un producto, indica la cantidad y pulsa **Añadir producto**. Usa **Cobrar venta** para registrar y generar el ticket.
5. **Configura la impresora** desde el botón dedicado. Se listan las impresoras que `lpstat -p` detecte, o puedes escribir el nombre manualmente.
6. Al **cerrar caja**, la app ofrece exportar un CSV con referencia y número de ventas. También imprime un ticket de cierre con el total de caja.

Los tickets siempre se guardan como texto en la carpeta `tickets` y, si hay impresora configurada, también se envían al comando `lpr`.
