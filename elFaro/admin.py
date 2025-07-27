from django.contrib import admin
from .models import Producto
from django import forms
from django.shortcuts import render, redirect
from django.urls import path, reverse
import csv
from io import TextIOWrapper
from .models import ImagenPromocion

admin.site.register(ImagenPromocion)

class CsvImportForm(forms.Form):
    csv_upload = forms.FileField(label="Archivo CSV")

@admin.register(Producto)
class ProductoAdmin(admin.ModelAdmin):
    list_display = ('nombre', 'codigo_barras', 'precio', 'precio_vecino', 'sku')
    search_fields = ('nombre', 'codigo_barras', 'sku')
    change_list_template = "admin/producto_changelist.html"

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('import-csv/', self.import_csv, name='import_csv'),
        ]
        return custom_urls + urls

    def changelist_view(self, request, extra_context=None):
        if not extra_context:
            extra_context = {}
        extra_context['import_csv_url'] = reverse('admin:import_csv')
        return super().changelist_view(request, extra_context=extra_context)

    def import_csv(self, request):
        if request.method == "POST":
            csv_file = request.FILES["csv_upload"]
            decoded_file = TextIOWrapper(csv_file, encoding='utf-8')
            reader = csv.DictReader(decoded_file)
            required_fields = ['codigo_barras', 'nombre', 'precio']
            if not all(field in reader.fieldnames for field in required_fields):
                self.message_user(request, "El archivo CSV debe tener las columnas obligatorias: codigo_barras, nombre, precio. Las columnas sku y precio_vecino son opcionales.", level='error')
                return redirect("..")
            
            productos_actualizados = 0
            productos_con_precio_vecino = 0
            errores = []
            
            for row_num, row in enumerate(reader, start=2):  # start=2 porque la primera fila son headers
                try:
                    # Validar y normalizar precio
                    precio_str = row['precio'].replace('.', '').replace(',', '.')
                    try:
                        precio = float(precio_str)
                        if precio > 9999999:
                            raise ValueError(f"Precio demasiado grande: {precio}")
                        if precio < 0:
                            raise ValueError(f"Precio negativo: {precio}")
                        # Convertir a entero si no tiene decimales
                        if precio == int(precio):
                            precio = int(precio)
                    except ValueError as e:
                        errores.append(f"Fila {row_num}: Precio inválido '{row['precio']}' - {e}")
                        continue
                    
                    defaults = {
                        'nombre': row['nombre'][:200],  # Limitar longitud
                        'precio': precio,
                        'sku': (row.get('sku', '') or None)[:100] if row.get('sku') else None,
                    }
                    
                    # Procesar precio_vecino si existe en el CSV
                    if 'precio_vecino' in row and row['precio_vecino']:
                        try:
                            precio_vecino_str = row['precio_vecino'].replace('.', '').replace(',', '.')
                            precio_vecino = float(precio_vecino_str)
                            if precio_vecino > 9999999:
                                raise ValueError(f"Precio vecino demasiado grande: {precio_vecino}")
                            if precio_vecino < 0:
                                raise ValueError(f"Precio vecino negativo: {precio_vecino}")
                            # Convertir a entero si no tiene decimales
                            if precio_vecino == int(precio_vecino):
                                precio_vecino = int(precio_vecino)
                            defaults['precio_vecino'] = precio_vecino
                            productos_con_precio_vecino += 1
                        except ValueError as e:
                            errores.append(f"Fila {row_num}: Precio vecino inválido '{row['precio_vecino']}' - {e}")
                            continue
                    else:
                        defaults['precio_vecino'] = None
                    
                    # Validar código de barras
                    codigo_barras = row['codigo_barras'][:30]  # Limitar longitud
                    if not codigo_barras:
                        errores.append(f"Fila {row_num}: Código de barras vacío")
                        continue
                    
                    Producto.objects.update_or_create(
                        codigo_barras=codigo_barras,
                        defaults=defaults
                    )
                    productos_actualizados += 1
                    
                except Exception as e:
                    errores.append(f"Fila {row_num}: Error inesperado - {str(e)}")
                    continue
                
            # Mostrar resultados
            mensaje = f"Importación completada: {productos_actualizados} productos actualizados"
            if productos_con_precio_vecino > 0:
                mensaje += f", {productos_con_precio_vecino} con precio vecino"
            
            if errores:
                mensaje += f". {len(errores)} errores encontrados"
                # Mostrar solo los primeros 10 errores para no saturar
                errores_mostrar = errores[:10]
                if len(errores) > 10:
                    errores_mostrar.append(f"... y {len(errores) - 10} errores más")
                
                self.message_user(request, mensaje, level='warning')
                for error in errores_mostrar:
                    self.message_user(request, error, level='error')
            else:
                self.message_user(request, mensaje + ".")
                
            return redirect("..")
        
        form = CsvImportForm()
        context = {
            "form": form,
            "opts": self.model._meta,
            "app_label": self.model._meta.app_label,
        }
        return render(request, "admin/csv_form.html", context)