import csv
import json
import os
import subprocess
import tkinter as tk
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Dict, List, Optional, Tuple


APP_DIR = Path.home() / ".pos_app"
APP_DIR.mkdir(parents=True, exist_ok=True)
STATE_FILE = APP_DIR / "app_state.json"
TICKET_DIR = APP_DIR / "tickets"


@dataclass
class Product:
    reference: str
    description: str
    barcode: str
    price: float


@dataclass
class SaleLine:
    product: Product
    qty: int
    price: float
    discount: float = 0.0  # porcentaje

    def total(self) -> float:
        return self.qty * self.price * (1 - self.discount / 100)


class POSApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Punto de Venta Simple")
        self.geometry("1200x750")

        self.products: List[Product] = []
        self.current_sale: List[SaleLine] = []
        self.session_sales: List[Tuple[List[SaleLine], float]] = []
        self.cash_open: bool = False
        self.printer_name: Optional[str] = None
        self.ticket_header: str = "*** Punto de venta ***"
        self.ticket_footer: str = "¡Gracias por su compra!"
        self.default_tax_rate: float = 21.0

        self._load_state()
        self._build_ui()

    # ---------- State handling ----------
    def _load_state(self) -> None:
        if STATE_FILE.exists():
            try:
                with open(STATE_FILE, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                self.products = [Product(**p) for p in data.get("products", [])]
                self.printer_name = data.get("printer_name")
                self.ticket_header = data.get("ticket_header", self.ticket_header)
                self.ticket_footer = data.get("ticket_footer", self.ticket_footer)
                self.default_tax_rate = data.get("default_tax_rate", self.default_tax_rate)
            except Exception:
                messagebox.showwarning("Estado", "No se pudo cargar el estado previo. Se iniciará limpio.")

    def _save_state(self) -> None:
        data = {
            "products": [asdict(p) for p in self.products],
            "printer_name": self.printer_name,
            "ticket_header": self.ticket_header,
            "ticket_footer": self.ticket_footer,
            "default_tax_rate": self.default_tax_rate,
        }
        try:
            with open(STATE_FILE, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
        except OSError as exc:
            messagebox.showerror("Estado", f"No se pudo guardar el estado: {exc}")

    # ---------- UI ----------
    def _build_ui(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", padding=6)
        style.configure("TLabelframe", padding=8)
        style.configure("TButton", padding=6)

        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        top_frame = ttk.Frame(self)
        top_frame.grid(row=0, column=0, sticky="ew", padx=12, pady=10)
        top_frame.columnconfigure(6, weight=1)

        ttk.Button(top_frame, text="Abrir caja", command=self.open_cash).grid(row=0, column=0, padx=6)
        ttk.Button(top_frame, text="Cerrar caja", command=self.close_cash).grid(row=0, column=1, padx=6)
        ttk.Button(top_frame, text="Configurar impresora", command=self.configure_printer).grid(row=0, column=2, padx=6)
        ttk.Button(top_frame, text="Plantilla ticket", command=self.configure_ticket_template).grid(row=0, column=3, padx=6)

        ttk.Button(top_frame, text="Cargar productos CSV", command=self.load_products_csv).grid(row=0, column=4, padx=6)
        ttk.Label(top_frame, text="Caja: ", font=("TkDefaultFont", 10, "bold")).grid(row=0, column=5, sticky="e")
        self.cash_status_var = tk.StringVar(value="Cerrada")
        self.cash_status_label = ttk.Label(top_frame, textvariable=self.cash_status_var, foreground="red")
        self.cash_status_label.grid(row=0, column=6, sticky="w")

        body = ttk.Frame(self)
        body.grid(row=1, column=0, sticky="nsew", padx=10, pady=10)
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        # Products panel
        products_frame = ttk.LabelFrame(body, text="Productos")
        products_frame.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        products_frame.columnconfigure(0, weight=1)
        products_frame.rowconfigure(1, weight=1)

        search_frame = ttk.Frame(products_frame)
        search_frame.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        search_frame.columnconfigure(1, weight=1)
        ttk.Label(search_frame, text="Buscar:").grid(row=0, column=0, padx=4)
        self.search_var = tk.StringVar()
        search_entry = ttk.Entry(search_frame, textvariable=self.search_var)
        search_entry.grid(row=0, column=1, sticky="ew", padx=4)
        search_entry.bind("<KeyRelease>", lambda _e: self._refresh_product_tree())
        search_entry.bind("<Return>", lambda _e: self._add_by_barcode())
        ttk.Label(search_frame, text="Filtrar por:").grid(row=0, column=2, padx=4)
        self.search_field_var = tk.StringVar(value="Todos")
        ttk.Combobox(
            search_frame,
            textvariable=self.search_field_var,
            state="readonly",
            values=["Todos", "Referencia", "Descripción", "Código de barras"],
            width=18,
        ).grid(row=0, column=3, padx=4)

        self.product_tree = ttk.Treeview(products_frame, columns=("ref", "desc", "bar", "price"), show="headings")
        for col, title, width in [
            ("ref", "Referencia", 120),
            ("desc", "Descripción", 250),
            ("bar", "Código barras", 150),
            ("price", "Precio", 100),
        ]:
            self.product_tree.heading(col, text=title)
            self.product_tree.column(col, width=width, anchor="w")
        self.product_tree.grid(row=1, column=0, sticky="nsew")

        prod_scroll = ttk.Scrollbar(products_frame, orient="vertical", command=self.product_tree.yview)
        self.product_tree.configure(yscrollcommand=prod_scroll.set)
        prod_scroll.grid(row=1, column=1, sticky="ns")

        # Sale panel
        sale_frame = ttk.LabelFrame(body, text="Venta actual")
        sale_frame.grid(row=0, column=1, sticky="nsew", padx=5, pady=5)
        sale_frame.columnconfigure(0, weight=1)
        sale_frame.rowconfigure(2, weight=1)

        qty_frame = ttk.Frame(sale_frame)
        qty_frame.grid(row=0, column=0, sticky="ew", padx=5, pady=5)
        qty_frame.columnconfigure(6, weight=1)
        ttk.Label(qty_frame, text="Cantidad:").grid(row=0, column=0, padx=5)
        self.qty_var = tk.StringVar(value="1")
        ttk.Entry(qty_frame, textvariable=self.qty_var, width=6).grid(row=0, column=1, padx=5)
        ttk.Label(qty_frame, text="Precio (opcional):").grid(row=0, column=2, padx=5)
        self.price_override_var = tk.StringVar()
        ttk.Entry(qty_frame, textvariable=self.price_override_var, width=10).grid(row=0, column=3, padx=5)
        ttk.Label(qty_frame, text="Dto %:").grid(row=0, column=4, padx=5)
        self.discount_var = tk.StringVar(value="0")
        ttk.Entry(qty_frame, textvariable=self.discount_var, width=6).grid(row=0, column=5, padx=5)
        ttk.Button(qty_frame, text="Añadir producto", command=self.add_product_to_sale).grid(row=0, column=6, padx=5, sticky="w")

        controls_frame = ttk.Frame(sale_frame)
        controls_frame.grid(row=1, column=0, sticky="ew", padx=5, pady=(0, 5))
        ttk.Button(controls_frame, text="Editar línea", command=self.edit_sale_line).grid(row=0, column=0, padx=5)
        ttk.Button(controls_frame, text="Eliminar línea", command=self.remove_sale_line).grid(row=0, column=1, padx=5)
        ttk.Label(controls_frame, text="IVA % venta:").grid(row=0, column=2, padx=5)
        self.tax_var = tk.StringVar(value=f"{self.default_tax_rate}")
        ttk.Spinbox(controls_frame, from_=0, to=30, textvariable=self.tax_var, width=6, increment=0.5).grid(row=0, column=3, padx=5)
        ttk.Button(controls_frame, text="Cobrar venta", command=self.finish_sale).grid(row=0, column=4, padx=5)

        self.sale_tree = ttk.Treeview(
            sale_frame,
            columns=("ref", "desc", "qty", "price", "discount", "total"),
            show="headings",
        )
        for col, title, width in [
            ("ref", "Referencia", 110),
            ("desc", "Descripción", 200),
            ("qty", "Cantidad", 80),
            ("price", "Precio", 90),
            ("discount", "Dto %", 70),
            ("total", "Total", 100),
        ]:
            self.sale_tree.heading(col, text=title)
            self.sale_tree.column(col, width=width, anchor="w")
        self.sale_tree.grid(row=2, column=0, sticky="nsew")
        self.sale_tree.bind("<Double-1>", lambda _e: self.edit_sale_line())

        sale_scroll = ttk.Scrollbar(sale_frame, orient="vertical", command=self.sale_tree.yview)
        self.sale_tree.configure(yscrollcommand=sale_scroll.set)
        sale_scroll.grid(row=2, column=1, sticky="ns")

        self.sale_total_var = tk.StringVar(value="Total: $0.00")
        ttk.Label(sale_frame, textvariable=self.sale_total_var, font=("TkDefaultFont", 11, "bold")).grid(row=3, column=0, sticky="e", padx=5, pady=8)

        self._refresh_product_tree()
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---------- CSV Import ----------
    def load_products_csv(self) -> None:
        csv_path = filedialog.askopenfilename(
            title="Selecciona CSV de productos",
            filetypes=[("CSV", "*.csv"), ("Todos", "*.*")],
        )
        if not csv_path:
            return

        with open(csv_path, newline="", encoding="utf-8") as fh:
            reader = csv.reader(fh)
            try:
                headers = next(reader)
            except StopIteration:
                messagebox.showerror("Importación", "El archivo está vacío")
                return
            sample_rows = [row for _, row in zip(range(3), reader)]

        self._open_mapping_dialog(csv_path, headers, sample_rows)

    def _open_mapping_dialog(self, csv_path: str, headers: List[str], sample_rows: List[List[str]]) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("Mapear columnas")
        dialog.grab_set()

        ttk.Label(dialog, text="Asigna cada campo obligatorio a una columna del CSV").grid(row=0, column=0, columnspan=2, padx=10, pady=5)

        field_labels = {
            "reference": "Referencia",
            "description": "Descripción",
            "barcode": "Código de barras",
            "price": "Precio de venta",
        }

        mappings: Dict[str, tk.StringVar] = {}
        for idx, (field, label) in enumerate(field_labels.items(), start=1):
            ttk.Label(dialog, text=label).grid(row=idx, column=0, sticky="e", padx=5, pady=3)
            var = tk.StringVar()
            cmb = ttk.Combobox(dialog, textvariable=var, values=headers, state="readonly")
            cmb.grid(row=idx, column=1, sticky="ew", padx=5, pady=3)
            if headers:
                cmb.current(min(idx - 1, len(headers) - 1))
            mappings[field] = var

        dialog.columnconfigure(1, weight=1)

        sample_frame = ttk.Labelframe(dialog, text="Vista previa")
        sample_frame.grid(row=len(field_labels) + 1, column=0, columnspan=2, sticky="nsew", padx=5, pady=5)

        preview = tk.Text(sample_frame, width=60, height=6, state="normal")
        preview.insert("1.0", ", ".join(headers) + "\n")
        for row in sample_rows:
            preview.insert("end", ", ".join(row) + "\n")
        preview.configure(state="disabled")
        preview.pack(fill="both", expand=True)

        def confirm() -> None:
            selected = {field: var.get() for field, var in mappings.items()}
            if len(set(selected.values())) < len(selected.values()):
                messagebox.showwarning("Importación", "Cada campo debe usar una columna diferente.")
                return
            dialog.destroy()
            self._import_products(csv_path, headers, selected)

        ttk.Button(dialog, text="Importar", command=confirm).grid(row=len(field_labels) + 2, column=0, columnspan=2, pady=5)

    def _import_products(self, csv_path: str, headers: List[str], mapping: Dict[str, str]) -> None:
        header_indices = {name: headers.index(col) for name, col in mapping.items()}
        imported = 0
        with open(csv_path, newline="", encoding="utf-8") as fh:
            reader = csv.reader(fh)
            next(reader)  # skip header
            for row in reader:
                try:
                    product = Product(
                        reference=row[header_indices["reference"]].strip(),
                        description=row[header_indices["description"]].strip(),
                        barcode=row[header_indices["barcode"]].strip(),
                        price=float(row[header_indices["price"]].replace(",", ".")),
                    )
                except (IndexError, ValueError):
                    continue
                self.products.append(product)
                imported += 1

        self._refresh_product_tree()
        self._save_state()
        messagebox.showinfo("Importación", f"Productos importados: {imported}")

    # ---------- Sales ----------
    def add_product_to_sale(self) -> None:
        selection = self.product_tree.selection()
        if not selection:
            messagebox.showwarning("Venta", "Selecciona un producto para añadir.")
            return
        try:
            qty = int(self.qty_var.get())
            if qty <= 0:
                raise ValueError
        except ValueError:
            messagebox.showwarning("Venta", "La cantidad debe ser un número entero positivo.")
            return

        item_id = selection[0]
        idx = int(self.product_tree.index(item_id))
        product = self.products[idx]
        price = self._parse_float_or_default(self.price_override_var.get(), product.price)
        discount = self._parse_float_or_default(self.discount_var.get(), 0.0)
        self.current_sale.append(SaleLine(product=product, qty=qty, price=price, discount=discount))
        self._refresh_sale_tree()

    def _add_by_barcode(self) -> None:
        code = self.search_var.get().strip() if hasattr(self, "search_var") else ""
        if not code:
            return
        try:
            qty = int(self.qty_var.get())
            if qty <= 0:
                raise ValueError
        except ValueError:
            messagebox.showwarning("Venta", "La cantidad debe ser un número entero positivo.")
            return
        for product in self.products:
            if code.lower() in (product.barcode.lower(), product.reference.lower()):
                price = self._parse_float_or_default(self.price_override_var.get(), product.price)
                discount = self._parse_float_or_default(self.discount_var.get(), 0.0)
                self.current_sale.append(SaleLine(product=product, qty=qty, price=price, discount=discount))
                self._refresh_sale_tree()
                self.search_var.set("")
                return
        messagebox.showinfo("Búsqueda", "No se encontró producto con ese código o referencia.")

    def _refresh_sale_tree(self) -> None:
        for row in self.sale_tree.get_children():
            self.sale_tree.delete(row)
        subtotal = 0.0
        for line in self.current_sale:
            line_total = line.total()
            subtotal += line_total
            self.sale_tree.insert(
                "",
                "end",
                values=(
                    line.product.reference,
                    line.product.description,
                    line.qty,
                    f"${line.price:,.2f}",
                    f"{line.discount:.2f}",
                    f"${line_total:,.2f}",
                ),
            )
        tax_rate = self._parse_float_or_default(self.tax_var.get(), self.default_tax_rate)
        tax_amount = subtotal * tax_rate / 100
        total = subtotal + tax_amount
        self.sale_total_var.set(f"Subtotal: ${subtotal:,.2f} | IVA {tax_rate:.2f}%: ${tax_amount:,.2f} | Total: ${total:,.2f}")

    def edit_sale_line(self) -> None:
        selection = self.sale_tree.selection()
        if not selection:
            messagebox.showinfo("Venta", "Selecciona una línea para editar.")
            return
        idx = int(self.sale_tree.index(selection[0]))
        line = self.current_sale[idx]

        dialog = tk.Toplevel(self)
        dialog.title("Editar línea")
        dialog.grab_set()

        ttk.Label(dialog, text=f"Producto: {line.product.reference}").grid(row=0, column=0, columnspan=2, padx=5, pady=5)
        ttk.Label(dialog, text="Cantidad:").grid(row=1, column=0, sticky="e", padx=5, pady=5)
        qty_var = tk.StringVar(value=str(line.qty))
        ttk.Entry(dialog, textvariable=qty_var, width=8).grid(row=1, column=1, padx=5, pady=5)

        ttk.Label(dialog, text="Precio:").grid(row=2, column=0, sticky="e", padx=5, pady=5)
        price_var = tk.StringVar(value=f"{line.price}")
        ttk.Entry(dialog, textvariable=price_var, width=10).grid(row=2, column=1, padx=5, pady=5)

        ttk.Label(dialog, text="Dto %:").grid(row=3, column=0, sticky="e", padx=5, pady=5)
        discount_var = tk.StringVar(value=f"{line.discount}")
        ttk.Entry(dialog, textvariable=discount_var, width=10).grid(row=3, column=1, padx=5, pady=5)

        def save_line() -> None:
            try:
                new_qty = int(qty_var.get())
                if new_qty <= 0:
                    raise ValueError
            except ValueError:
                messagebox.showerror("Venta", "Cantidad inválida.")
                return
            new_price = self._parse_float_or_default(price_var.get(), line.price)
            new_discount = self._parse_float_or_default(discount_var.get(), line.discount)
            self.current_sale[idx] = SaleLine(line.product, new_qty, new_price, new_discount)
            self._refresh_sale_tree()
            dialog.destroy()

        ttk.Button(dialog, text="Guardar", command=save_line).grid(row=4, column=0, columnspan=2, pady=8)
        dialog.columnconfigure(1, weight=1)

    def remove_sale_line(self) -> None:
        selection = self.sale_tree.selection()
        if not selection:
            messagebox.showinfo("Venta", "Selecciona una línea para eliminar.")
            return
        idx = int(self.sale_tree.index(selection[0]))
        self.current_sale.pop(idx)
        self._refresh_sale_tree()

    def finish_sale(self) -> None:
        if not self.cash_open:
            messagebox.showwarning("Caja", "Debes abrir la caja antes de cobrar.")
            return
        if not self.current_sale:
            messagebox.showinfo("Venta", "No hay productos en la venta actual.")
            return
        tax_rate = self._parse_float_or_default(self.tax_var.get(), self.default_tax_rate)
        self.default_tax_rate = tax_rate
        sale_copy = [SaleLine(line.product, line.qty, line.price, line.discount) for line in self.current_sale]
        self.session_sales.append((sale_copy, tax_rate))
        self._print_ticket_for_sale(sale_copy, tax_rate)
        self.current_sale = []
        self._refresh_sale_tree()
        self._save_state()
        messagebox.showinfo("Venta", "Venta registrada y ticket listo.")

    # ---------- Cash register ----------
    def open_cash(self) -> None:
        if self.cash_open:
            messagebox.showinfo("Caja", "La caja ya está abierta.")
            return
        self.cash_open = True
        self.session_sales.clear()
        self.cash_status_var.set("Abierta")
        self.cash_status_var_label_color("green")
        if hasattr(self, "tax_var"):
            self.tax_var.set(f"{self.default_tax_rate}")

    def close_cash(self) -> None:
        if not self.cash_open:
            messagebox.showinfo("Caja", "La caja ya está cerrada.")
            return

        export = messagebox.askyesno("Cierre", "¿Exportar CSV con ventas del día?")
        if export:
            self._export_session_csv()

        summary_text = self._build_cash_summary()
        self._print_text(summary_text)
        messagebox.showinfo("Cierre", "Caja cerrada. Ticket de cierre listo.")

        self.cash_open = False
        self.session_sales.clear()
        self.cash_status_var.set("Cerrada")
        self.cash_status_var_label_color("red")

    def cash_status_var_label_color(self, color: str) -> None:
        self.cash_status_label.configure(foreground=color)

    def _build_cash_summary(self) -> str:
        total = 0.0
        aggregated: Dict[str, int] = {}
        tax_total = 0.0
        for sale_lines, tax_rate in self.session_sales:
            subtotal_sale = 0.0
            for line in sale_lines:
                aggregated[line.product.reference] = aggregated.get(line.product.reference, 0) + line.qty
                subtotal_sale += line.total()
            tax_total += subtotal_sale * tax_rate / 100
            total += subtotal_sale + (subtotal_sale * tax_rate / 100)
        base_total = total - tax_total
        lines = ["*** Cierre de caja ***", datetime.now().strftime("%d/%m/%Y %H:%M"), ""]
        for ref, qty in aggregated.items():
            lines.append(f"{ref}: {qty} uds")
        lines.append("")
        lines.append(f"Base imponible: ${base_total:,.2f}")
        lines.append(f"IVA acumulado: ${tax_total:,.2f}")
        lines.append(f"Total caja: ${total:,.2f}")
        return "\n".join(lines)

    def _export_session_csv(self) -> None:
        if not self.session_sales:
            messagebox.showinfo("Exportación", "No hay ventas registradas en esta sesión.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
            title="Guardar resumen de ventas",
        )
        if not path:
            return
        aggregated: Dict[str, int] = {}
        for sale_lines, _ in self.session_sales:
            for line in sale_lines:
                aggregated[line.product.reference] = aggregated.get(line.product.reference, 0) + line.qty
        with open(path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["referencia", "numero_ventas"])
            for ref, qty in aggregated.items():
                writer.writerow([ref, qty])

    # ---------- Printing ----------
    def configure_printer(self) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("Configurar impresora")
        dialog.grab_set()

        ttk.Label(dialog, text="Impresora térmica (lpstat -p):").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        printers = self._list_printers()
        self.printer_var = tk.StringVar(value=self.printer_name or (printers[0] if printers else ""))
        printer_combo = ttk.Combobox(dialog, textvariable=self.printer_var, values=printers)
        printer_combo.grid(row=1, column=0, padx=5, pady=5, sticky="ew")

        ttk.Label(dialog, text="Si no aparece, escribe el nombre manualmente.").grid(row=2, column=0, padx=5, pady=5, sticky="w")

        def save_printer() -> None:
            self.printer_name = self.printer_var.get().strip() or None
            self._save_state()
            dialog.destroy()

        ttk.Button(dialog, text="Guardar", command=save_printer).grid(row=3, column=0, pady=5)
        dialog.columnconfigure(0, weight=1)

    def configure_ticket_template(self) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("Plantilla de ticket")
        dialog.grab_set()

        ttk.Label(dialog, text="Encabezado:").grid(row=0, column=0, sticky="w", padx=5, pady=5)
        header_text = tk.Text(dialog, width=50, height=3)
        header_text.insert("1.0", self.ticket_header)
        header_text.grid(row=1, column=0, padx=5, pady=5, sticky="ew")

        ttk.Label(dialog, text="Pie de página:").grid(row=2, column=0, sticky="w", padx=5, pady=5)
        footer_text = tk.Text(dialog, width=50, height=3)
        footer_text.insert("1.0", self.ticket_footer)
        footer_text.grid(row=3, column=0, padx=5, pady=5, sticky="ew")

        ttk.Label(dialog, text="IVA por defecto (%):").grid(row=4, column=0, sticky="w", padx=5, pady=(5, 0))
        tax_entry = ttk.Spinbox(dialog, from_=0, to=30, increment=0.5, width=6)
        tax_entry.insert(0, f"{self.default_tax_rate}")
        tax_entry.grid(row=5, column=0, padx=5, pady=(0, 10), sticky="w")

        def save_template() -> None:
            self.ticket_header = header_text.get("1.0", "end").strip() or self.ticket_header
            self.ticket_footer = footer_text.get("1.0", "end").strip()
            self.default_tax_rate = self._parse_float_or_default(tax_entry.get(), self.default_tax_rate)
            if hasattr(self, "tax_var"):
                self.tax_var.set(f"{self.default_tax_rate}")
            self._save_state()
            dialog.destroy()

        ttk.Button(dialog, text="Guardar", command=save_template).grid(row=6, column=0, pady=5)
        dialog.columnconfigure(0, weight=1)

    def _list_printers(self) -> List[str]:
        try:
            output = subprocess.check_output(["lpstat", "-p"], text=True)
        except Exception:
            return []
        printers = []
        for line in output.splitlines():
            if line.startswith("printer "):
                printers.append(line.split()[1])
        return printers

    def _print_ticket_for_sale(self, sale: List[SaleLine], tax_rate: float) -> None:
        lines = [self.ticket_header, datetime.now().strftime("%d/%m/%Y %H:%M"), ""]
        subtotal = 0.0
        for line in sale:
            subtotal += line.total()
            discount_text = f" (-{line.discount:.2f}%)" if line.discount else ""
            lines.append(f"{line.product.reference} x{line.qty} @ ${line.price:,.2f}{discount_text}")
            lines.append(f"  {line.product.description}")
        lines.append("")
        tax_amount = subtotal * tax_rate / 100
        total = subtotal + tax_amount
        lines.append(f"Base: ${subtotal:,.2f}")
        lines.append(f"IVA {tax_rate:.2f}%: ${tax_amount:,.2f}")
        lines.append(f"TOTAL: ${total:,.2f}")
        if self.ticket_footer:
            lines.append("")
            lines.append(self.ticket_footer)
        self._print_text("\n".join(lines))

    def _print_text(self, text: str) -> None:
        try:
            TICKET_DIR.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            ticket_file = TICKET_DIR / f"ticket_{timestamp}.txt"
            with open(ticket_file, "w", encoding="utf-8") as fh:
                fh.write(text)
        except OSError as exc:
            messagebox.showerror("Impresión", f"No se pudo guardar el ticket: {exc}")
            return

        if not self.printer_name:
            messagebox.showinfo("Impresión", "No hay impresora configurada. Se guardó el ticket en la carpeta 'tickets'.")
            return

        try:
            process = subprocess.run(
                ["lpr", "-P", self.printer_name],
                input=text,
                text=True,
                capture_output=True,
                check=True,
            )
            if process.stderr:
                messagebox.showwarning("Impresión", f"Impresora respondió: {process.stderr}")
        except FileNotFoundError:
            messagebox.showwarning(
                "Impresión",
                "No se encontró el comando lpr. Se guardó el ticket en la carpeta 'tickets'.",
            )
        except subprocess.CalledProcessError as err:
            messagebox.showerror(
                "Impresión",
                f"No se pudo enviar a la impresora. Ticket guardado en 'tickets'.\n{err.stderr}",
            )

    # ---------- Helpers ----------
    def _refresh_product_tree(self) -> None:
        for row in self.product_tree.get_children():
            self.product_tree.delete(row)
        query = self.search_var.get().strip().lower() if hasattr(self, "search_var") else ""
        field = self.search_field_var.get() if hasattr(self, "search_field_var") else "Todos"
        for product in self.products:
            haystack = {
                "Referencia": product.reference.lower(),
                "Descripción": product.description.lower(),
                "Código de barras": product.barcode.lower(),
            }
            if query:
                if field == "Todos" and not (
                    query in haystack["Referencia"]
                    or query in haystack["Descripción"]
                    or query in haystack["Código de barras"]
                ):
                    continue
                if field != "Todos" and query not in haystack.get(field, ""):
                    continue
            self.product_tree.insert(
                "",
                "end",
                values=(
                    product.reference,
                    product.description,
                    product.barcode,
                    f"${product.price:,.2f}",
                ),
            )

    def _parse_float_or_default(self, value: str, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def on_close(self) -> None:
        self._save_state()
        self.destroy()


def main() -> None:
    app = POSApp()
    app.mainloop()


if __name__ == "__main__":
    main()
