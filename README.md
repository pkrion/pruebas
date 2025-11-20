# Punto de Venta de Escritorio

Aplicación de escritorio con Tkinter para gestionar ventas con tickets en impresora térmica, buscador rápido y edición de líneas.

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
3. **Abre caja** con el botón "Abrir caja" para empezar a registrar ventas (resetea la sesión de ventas).
4. Busca por referencia, descripción o código de barras (incluye lector láser) y añade productos indicando cantidad, precio opcional y descuento. Puedes editar o eliminar líneas de la venta, ajustar el IVA por ticket y finalizar con **Cobrar venta**.
5. **Plantilla ticket** permite ajustar encabezado, pie de página e IVA por defecto. El IVA se desglosa al imprimir.
6. **Configura la impresora** desde el botón dedicado. Se listan las impresoras que `lpstat -p` detecte, o puedes escribir el nombre manualmente.
7. Al **cerrar caja**, la app ofrece exportar un CSV con referencia y número de ventas. También imprime un ticket de cierre con base imponible, IVA acumulado y total de caja.

Los tickets y el estado se guardan en la carpeta del usuario `~/.pos_app` (evita errores de permisos) y, si hay impresora configurada, también se envían al comando `lpr`.
