from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from .models import Producto, ImagenPromocion
from .forms import ProductoForm
import re
import csv
from django.http import HttpResponse
from django.contrib.admin.views.decorators import staff_member_required
import requests
from bs4 import BeautifulSoup
import json
import time
import threading
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.conf import settings
from datetime import datetime
from urllib.parse import quote
from urllib.parse import urlparse


def limpiar_codigo_barras(codigo):
    # Elimina espacios, tabulaciones, saltos de línea y retornos de carro
    return re.sub(r'[\s\r\n\t]+', '', codigo)


def buscar_producto(request):
    codigo = request.GET.get('codigo_barras', '')
    codigo_original = codigo
    codigo = limpiar_codigo_barras(codigo)
    print(f"Código recibido en backend (limpio): '{codigo}'")

    # Obtener IP del cliente para el reporte
    ip_cliente = request.META.get('HTTP_X_FORWARDED_FOR')
    if ip_cliente:
        ip_cliente = ip_cliente.split(',')[0]
    else:
        ip_cliente = request.META.get('REMOTE_ADDR', 'No disponible')

    # Verificar si se solicita búsqueda exacta
    busqueda_exacta = request.GET.get('busqueda_exacta') == 'true'
    exacto = request.GET.get('exacto') == '1'
    no_similar = request.GET.get('no_similar') == '1'

    if not codigo:
        return JsonResponse({'error': 'Código de barras no proporcionado'}, status=400)
    if len(codigo) > 14:
        return JsonResponse({'error': 'Código de barras demasiado largo'}, status=400)
    
    try:
        # Paso 1: Intentar búsqueda exacta primero
        producto = None
        try:
            producto = Producto.objects.filter(codigo_barras=codigo).first()
        except Exception as e:
            print(f"Error en búsqueda exacta: {e}")
            # Si hay error, intentar búsqueda más específica
            from django.db import connection
            with connection.cursor() as cursor:
                cursor.execute("SELECT id, codigo_barras, nombre, precio, precio_vecino, sku FROM elFaro_producto WHERE codigo_barras = ?", [codigo])
                row = cursor.fetchone()
                if row:
                    # Validar que los datos sean válidos antes de crear el objeto
                    try:
                        precio = float(row[3]) if row[3] is not None else 0
                        precio_vecino = float(row[4]) if row[4] is not None else None
                        
                        # Verificar que los precios sean válidos
                        if precio > 9999999 or (precio_vecino and precio_vecino > 9999999):
                            # Eliminar producto corrupto
                            cursor.execute("DELETE FROM elFaro_producto WHERE id = ?", [row[0]])
                            print(f"Eliminado producto corrupto ID {row[0]} con precios inválidos")
                        else:
                            # Crear objeto producto manualmente si los datos son válidos
                            producto = type('Producto', (), {
                                'id': row[0],
                                'codigo_barras': row[1],
                                'nombre': row[2],
                                'precio': precio,
                                'precio_vecino': precio_vecino,
                                'sku': row[5]
                            })()
                    except (ValueError, TypeError) as ve:
                        print(f"Datos corruptos en producto ID {row[0]}: {ve}")
                        # Eliminar producto con datos corruptos
                        cursor.execute("DELETE FROM elFaro_producto WHERE id = ?", [row[0]])
        
        # Si se solicita SOLO búsqueda exacta, no hacer búsquedas adicionales
        if busqueda_exacta and exacto and no_similar:
            # Solo intentar con/sin cero inicial para códigos que empiezan con 0
            if not producto and codigo.startswith('0'):
                sin_ceros = codigo.lstrip('0')
                if sin_ceros:  # Asegurar que no quede vacío
                    try:
                        producto = Producto.objects.filter(codigo_barras=sin_ceros).first()
                        if producto:
                            print(f"Encontrado sin cero inicial: {producto.codigo_barras}")
                    except Exception as e:
                        print(f"Error buscando sin ceros: {e}")
            
            # También intentar agregando un cero si no se encontró
            if not producto and not codigo.startswith('0'):
                codigo_con_cero = '0' + codigo
                try:
                    producto = Producto.objects.filter(codigo_barras=codigo_con_cero).first()
                    if producto:
                        print(f"Encontrado con cero inicial: {producto.codigo_barras}")
                except Exception as e:
                    print(f"Error buscando con cero: {e}")
        else:
            # Lógica de búsqueda flexible original (solo si NO es búsqueda exacta)
            if not producto:
                # Intentar sin ceros iniciales (si comienza con 0)
                if codigo.startswith('0'):
                    sin_ceros = codigo.lstrip('0')
                    if sin_ceros:  # Asegurar que no quede vacío
                        try:
                            producto = Producto.objects.filter(codigo_barras=sin_ceros).first()
                        except Exception as e:
                            print(f"Error buscando sin ceros: {e}")
                else:
                    # Intentar añadiendo ceros iniciales (hasta 13 o 14 dígitos)
                    for i in range(1, 5):  # Probar añadiendo de 1 a 4 ceros
                        codigo_con_ceros = '0' * i + codigo
                        if len(codigo_con_ceros) in (13, 14):  # Si llegamos a 13 o 14 dígitos
                            try:
                                producto = Producto.objects.filter(codigo_barras=codigo_con_ceros).first()
                                if producto:
                                    break
                            except Exception as e:
                                print(f"Error buscando con ceros: {e}")
            
            # Paso 3: Si todavía no hay coincidencia, buscar en toda la base de datos por similitud
            if not producto:
                try:
                    # Verificar en la base de datos por coincidencias con los mismos dígitos sin importar el orden
                    todos_productos = Producto.objects.all()
                    for p in todos_productos:
                        # Si los mismos dígitos están presentes (sin importar orden)
                        if len(p.codigo_barras) == len(codigo) and sorted(p.codigo_barras) == sorted(codigo):
                            producto = p
                            print(f"Coincidencia por dígitos similares: {p.codigo_barras}")
                            break
                        
                        # Probar con código con o sin ceros iniciales
                        codigo_db_sin_ceros = p.codigo_barras.lstrip('0')
                        codigo_scan_sin_ceros = codigo.lstrip('0')
                        
                        if codigo_db_sin_ceros == codigo_scan_sin_ceros:
                            producto = p
                            print(f"Coincidencia sin ceros iniciales: {p.codigo_barras}")
                            break
                        
                        # Verificar si los códigos contienen los mismos dígitos (posible inversión)
                        # Por ejemplo, 417890039120 vs 041789003912
                        if len(codigo_db_sin_ceros) == len(codigo_scan_sin_ceros) and set(codigo_db_sin_ceros) == set(codigo_scan_sin_ceros):
                            # Si hay al menos 60% de coincidencia posicional
                            coincidencias = sum(1 for a, b in zip(codigo_db_sin_ceros, codigo_scan_sin_ceros) if a == b)
                            if coincidencias / len(codigo_db_sin_ceros) >= 0.6:
                                producto = p
                                print(f"Posible inversión/desorden detectada: {codigo} vs {p.codigo_barras}")
                                break
                except Exception as e:
                    print(f"Error en búsqueda avanzada: {e}")
        
        if producto:
            print(f"✅ Producto encontrado: {producto.nombre} con código {producto.codigo_barras}")
            return JsonResponse({
                'nombre': producto.nombre,
                'precio': str(producto.precio),
                'sku': producto.sku or '',
                'codigo_barras': producto.codigo_barras,
                'codigo_original': codigo_original,
                'precio_vecino': str(producto.precio_vecino) if producto.precio_vecino else None
            })
        
        # Si llegamos aquí, no se encontró el producto
        print(f"❌ PRODUCTO NO ENCONTRADO para código: {codigo}")
        
        # Enviar correo de notificación en un hilo separado
        def enviar_correo_async():
            try:
                print(f"📧 [CORREO] Iniciando envío para código: {codigo}")
                print(f"📧 [CORREO] IP cliente: {ip_cliente}")
                print(f"📧 [CORREO] Email configurado: {getattr(settings, 'EMAIL_HOST_USER', 'NO CONFIGURADO')}")
                print(f"📧 [CORREO] Admin email: {getattr(settings, 'ADMIN_EMAIL', 'NO CONFIGURADO')}")
                
                resultado = enviar_notificacion_producto_no_encontrado(codigo, ip_cliente)
                
                if resultado:
                    print(f"✅ [CORREO] Envío exitoso")
                else:
                    print(f"❌ [CORREO] Error en envío")
                    
            except Exception as e:
                print(f"💥 [CORREO] Excepción: {e}")
                import traceback
                print(f"💥 [CORREO] Traceback: {traceback.format_exc()}")
        
        # Ejecutar en segundo plano para no bloquear la respuesta
        hilo_correo = threading.Thread(target=enviar_correo_async)
        hilo_correo.daemon = True
        hilo_correo.start()
        print(f"🚀 Hilo de correo iniciado en segundo plano")
        
        return JsonResponse({
            'error': 'Producto no encontrado',
            'codigo_escaneado': codigo
        }, status=404)
        
    except Exception as e:
        print('💥 Error en buscar_producto:', str(e))
        return JsonResponse({'error': 'Error interno: ' + str(e)}, status=500)


def lector_precios(request):
    try:
        # Intentar cargar productos con manejo de errores
        productos = []
        productos_con_errores = []
        
        # Cargar productos de forma segura
        try:
            productos = list(Producto.objects.all())
        except Exception as e:
            # Si hay error al cargar todos, intentar cargar uno por uno
            print(f"Error al cargar productos masivamente: {e}")
            from decimal import InvalidOperation
            
            # Obtener IDs de todos los productos primero
            from django.db import connection
            with connection.cursor() as cursor:
                cursor.execute("SELECT id FROM elFaro_producto")
                product_ids = [row[0] for row in cursor.fetchall()]
            
            # Cargar productos uno por uno, saltando los corruptos
            for product_id in product_ids:
                try:
                    producto = Producto.objects.get(id=product_id)
                    productos.append(producto)
                except (InvalidOperation, Exception) as e:
                    productos_con_errores.append(product_id)
                    print(f"Error al cargar producto ID {product_id}: {e}")
            
            # Si hay productos con errores, eliminarlos
            if productos_con_errores:
                print(f"Eliminando {len(productos_con_errores)} productos corruptos...")
                with connection.cursor() as cursor:
                    placeholders = ','.join(['?' for _ in productos_con_errores])
                    cursor.execute(f"DELETE FROM elFaro_producto WHERE id IN ({placeholders})", productos_con_errores)
                
                # Mostrar mensaje de advertencia
                if request.user.is_staff:
                    messages.warning(request, f"Se eliminaron {len(productos_con_errores)} productos con datos corruptos.")
        
        # Cargar imágenes de promociones
        imagenes_promociones = ImagenPromocion.objects.all()
        
        return render(request, 'elFaro/lector_precios.html', {
            'productos': productos,
            'imagenes_promociones': imagenes_promociones,
        })
        
    except Exception as e:
        print(f"Error crítico en lector_precios: {e}")
        # En caso de error crítico, mostrar página con mensaje de error
        return render(request, 'elFaro/lector_precios.html', {
            'productos': [],
            'imagenes_promociones': [],
            'error_mensaje': f"Error al cargar datos: {str(e)}"
        })


def mantenedor_promociones(request):
    if request.method == 'POST':
        if 'eliminar_id' in request.POST:
            ImagenPromocion.objects.filter(id=request.POST['eliminar_id']).delete()
        elif 'imagen' in request.FILES:
            ImagenPromocion.objects.create(
                imagen=request.FILES['imagen'],
                nombre=request.POST.get('nombre', '')
            )
        return redirect('mantenedor_promociones')
    imagenes = ImagenPromocion.objects.all()
    return render(request, 'elFaro/mantenedor_promociones.html', {'imagenes': imagenes})


def agregar_producto(request):
    if request.method == 'POST':
        form = ProductoForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Producto agregado correctamente.')
            return redirect('agregar_producto')
    else:
        form = ProductoForm()
    return render(request, 'elFaro/agregar_producto.html', {'form': form})


def lista_productos(request):
    productos = Producto.objects.all()
    return render(request, 'elFaro/lista_productos.html', {'productos': productos})


def editar_producto(request, producto_id):
    producto = get_object_or_404(Producto, id=producto_id)
    if request.method == 'POST':
        form = ProductoForm(request.POST, instance=producto)
        if form.is_valid():
            form.save()
            return redirect('lista_productos')
    else:
        form = ProductoForm(instance=producto)
    return render(request, 'elFaro/editar_producto.html', {'form': form, 'producto': producto})


def eliminar_producto(request, producto_id):
    producto = get_object_or_404(Producto, id=producto_id)
    if request.method == 'POST':
        producto.delete()
        return redirect('lista_productos')
    return redirect('lista_productos')


@staff_member_required
def export_productos_csv(request):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="productos.csv"'
    
    # Crear el escritor CSV
    writer = csv.writer(response)
    
    # Escribir encabezados
    writer.writerow(['codigo_barras', 'nombre', 'precio', 'precio_vecino', 'sku'])
    
    # Escribir datos de productos
    productos = Producto.objects.all()
    for producto in productos:
        # Convertir None a cadena vacía para evitar errores en CSV
        precio_vecino = producto.precio_vecino if producto.precio_vecino else ''
        sku = producto.sku if producto.sku else ''
        
        writer.writerow([
            producto.codigo_barras,
            producto.nombre,
            producto.precio,
            precio_vecino,
            sku
        ])
    
    return response


def test_email(request):
    """
    Función temporal para probar el envío de correo
    """
    try:
        print(f"📧 [TEST] Probando configuración de correo...")
        print(f"📧 [TEST] EMAIL_HOST_USER: {getattr(settings, 'EMAIL_HOST_USER', 'NO CONFIGURADO')}")
        print(f"📧 [TEST] ADMIN_EMAIL: {getattr(settings, 'ADMIN_EMAIL', 'NO CONFIGURADO')}")
        
        resultado = send_mail(
            subject='🧪 Prueba de correo - El Faro',
            message='Este es un correo de prueba para verificar la configuración.',
            from_email=getattr(settings, 'NOTIFICATION_FROM_EMAIL', 'no-configurado@test.com'),
            recipient_list=[getattr(settings, 'ADMIN_EMAIL', 'admin@test.com')],
            fail_silently=False
        )
        
        if resultado:
            print(f"✅ [TEST] Correo de prueba enviado exitosamente")
            return JsonResponse({'status': 'success', 'message': 'Correo enviado exitosamente'})
        else:
            print(f"❌ [TEST] Error enviando correo de prueba")
            return JsonResponse({'status': 'error', 'message': 'Error enviando correo'})
            
    except Exception as e:
        print(f"💥 [TEST] Error en prueba de correo: {e}")
        return JsonResponse({'status': 'error', 'message': f'Error: {str(e)}'})


def buscar_producto_en_internet(codigo_barras):
    """
    Busca información del producto en APIs públicas
    """
    print(f"🔍 [INTERNET] ===== BÚSQUEDA EN INTERNET =====")
    print(f"🔍 [INTERNET] Código: {codigo_barras}")
    
    resultados = {
        'encontrado': False,
        'nombre': '',
        'descripcion': '',
        'marca': '',
        'categoria': '',
        'fuente': '',
        'imagen_url': '',
        'precio_referencia': '',
        'link_producto': ''
    }
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    
    # ===== FUENTE 1: Open Food Facts =====
    try:
        print(f"🌐 [1] OPEN FOOD FACTS - Código: {codigo_barras}")
        
        url = f"https://world.openfoodfacts.org/api/v0/product/{codigo_barras}.json"
        response = requests.get(url, timeout=15)
        print(f"📊 [1] Status HTTP: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"📊 [1] Status en respuesta: {data.get('status')}")
            
            if data.get('status') == 1:
                producto = data.get('product', {})
                
                # Buscar nombre en múltiples idiomas
                nombres_posibles = [
                    producto.get('product_name_es', ''),
                    producto.get('product_name', ''),
                    producto.get('product_name_en', ''),
                    producto.get('abbreviated_product_name', ''),
                    producto.get('generic_name_es', ''),
                    producto.get('generic_name', '')
                ]
                
                nombre = ''
                for n in nombres_posibles:
                    if n and len(n.strip()) > 3:
                        nombre = n.strip()
                        break
                
                if nombre:
                    resultados.update({
                        'encontrado': True,
                        'nombre': nombre,
                        'descripcion': producto.get('generic_name', ''),
                        'marca': producto.get('brands', ''),
                        'categoria': producto.get('categories_tags', [])[:3] if producto.get('categories_tags') else producto.get('categories', ''),
                        'imagen_url': producto.get('image_url', '') or producto.get('image_front_url', ''),
                        'link_producto': f"https://www.google.cl/search?q={nombre.replace(' ', '+')}+chile",
                        'precio_referencia': 'Consultar en tienda',
                        'fuente': 'Open Food Facts'
                    })
                    
                    print(f"✅ [1] ===== ENCONTRADO EN OPEN FOOD FACTS =====")
                    print(f"📦 [1] Nombre: {nombre}")
                    print(f"🏷️ [1] Marca: {resultados['marca']}")
                    return resultados
            
            print(f"❌ [1] Open Food Facts: producto no encontrado")
        else:
            print(f"❌ [1] Open Food Facts: Error HTTP {response.status_code}")
    
    except Exception as e:
        print(f"❌ [1] Error en Open Food Facts: {e}")
    
    # ===== FUENTE 2: UPC Database =====
    try:
        print(f"🔍 [2] UPC DATABASE - Código: {codigo_barras}")
        
        url = f"https://api.upcitemdb.com/prod/trial/lookup?upc={codigo_barras}"
        response = requests.get(url, timeout=10)
        print(f"📊 [2] Status HTTP: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"📊 [2] Response code: {data.get('code')}")
            
            if data.get('code') == 'OK' and data.get('items'):
                item = data['items'][0]
                nombre = item.get('title', '')
                
                if nombre and len(nombre) > 3:
                    resultados.update({
                        'encontrado': True,
                        'nombre': nombre,
                        'descripcion': item.get('description', ''),
                        'marca': item.get('brand', ''),
                        'categoria': item.get('category', ''),
                        'imagen_url': item.get('images', [''])[0] if item.get('images') else '',
                        'link_producto': f"https://www.google.cl/search?q={nombre.replace(' ', '+')}+chile",
                        'precio_referencia': 'Consultar en tienda',
                        'fuente': 'UPC Database'
                    })
                    
                    print(f"✅ [2] ===== ENCONTRADO EN UPC DATABASE =====")
                    print(f"📦 [2] Nombre: {nombre}")
                    return resultados
            
            print(f"❌ [2] UPC Database: no encontrado")
        else:
            print(f"❌ [2] UPC Database: Error HTTP {response.status_code}")
    
    except Exception as e:
        print(f"❌ [2] Error en UPC Database: {e}")
    
    print(f"❌ [INTERNET] No se encontró información en internet")
    return resultados


def enviar_notificacion_producto_no_encontrado(codigo_barras, ip_cliente=None):
    """
    Envía correo cuando no se encuentra un producto - CON RESULTADOS DE GOOGLE
    """
    try:
        print(f"📧 [EMAIL] ===== INICIANDO PROCESO DE ENVÍO =====")
        print(f"📧 [EMAIL] Código: {codigo_barras}")
        
        tiempo_inicio = time.time()
        
        # Buscar información del producto en internet (APIs)
        print(f"🔍 [EMAIL] Buscando en APIs...")
        info_producto = buscar_producto_en_internet(codigo_barras)
        
        # Buscar resultados en Google
        print(f"🔍 [EMAIL] Buscando en Google...")
        resultados_google, tiempo_google = buscar_resultados_google(codigo_barras, max_resultados=6)
        
        tiempo_total = round(time.time() - tiempo_inicio, 2)
        
        # Datos para el correo
        contexto = {
            'codigo_barras': codigo_barras,
            'fecha_hora': datetime.now().strftime('%d/%m/%Y %H:%M:%S'),
            'ip_cliente': ip_cliente or 'No disponible',
            'producto_sugerido': info_producto,
            'encontrado_en_internet': info_producto['encontrado'],
            'resultados_google': resultados_google,
            'tiempo_busqueda': tiempo_total
        }
        
        # Log del resultado de la búsqueda
        print(f"📧 [EMAIL] ===== RESUMEN BÚSQUEDAS =====")
        print(f"📧 [EMAIL] APIs encontradas: {info_producto['encontrado']}")
        print(f"📧 [EMAIL] Google resultados: {len(resultados_google)}")
        print(f"📧 [EMAIL] Tiempo total: {tiempo_total}s")
        
        if info_producto['encontrado']:
            print(f"📧 [EMAIL] API: {info_producto['nombre']} - {info_producto['fuente']}")
        
        for i, resultado in enumerate(resultados_google[:3]):
            print(f"📧 [EMAIL] Google {i+1}: {resultado['title'][:50]}...")
        
        # Renderizar el template del correo
        mensaje_html = None
        try:
            mensaje_html = render_to_string('elFaro/email_producto_no_encontrado.html', contexto)
            print(f"📧 [EMAIL] ✅ Template HTML renderizado correctamente")
        except Exception as template_error:
            print(f"⚠️ [EMAIL] Error renderizando template HTML: {template_error}")
        
        # Crear mensaje de texto mejorado
        seccion_google = ""
        if resultados_google:
            seccion_google = f"""🔍 RESULTADOS DE GOOGLE ({len(resultados_google)} encontrados):

"""
            for i, resultado in enumerate(resultados_google[:3], 1):
                seccion_google += f"""{i}. {resultado['title']}
   🔗 {resultado['link']}
   📝 {resultado['snippet'][:100]}...
   🌐 Fuente: {resultado['display_link']}

"""
        else:
            seccion_google = "🔍 NO SE ENCONTRARON RESULTADOS EN GOOGLE"
        
        seccion_apis = ""
        if info_producto['encontrado']:
            seccion_apis = f"""✅ INFORMACIÓN DE APIs:

📦 Nombre: {info_producto['nombre']}
{f"🏷️ Marca: {info_producto['marca']}" if info_producto['marca'] else ""}
{f"📝 Descripción: {info_producto['descripcion']}" if info_producto['descripcion'] else ""}
🔗 Fuente: {info_producto['fuente']}
{f"🛒 Link: {info_producto['link_producto']}" if info_producto['link_producto'] else ""}"""
        else:
            seccion_apis = "❌ NO SE ENCONTRÓ INFORMACIÓN EN APIs"

        mensaje_texto = f"""PRODUCTO NO ENCONTRADO - El Faro Algarrobo

Se ha buscado un producto que no existe en la base de datos:

📊 INFORMACIÓN DE BÚSQUEDA:
• Código de barras: {codigo_barras}
• Fecha y hora: {contexto['fecha_hora']}
• IP del cliente: {contexto['ip_cliente']}
• Tiempo de búsqueda: {tiempo_total}s

{seccion_google}

{seccion_apis}

💡 ACCIONES RECOMENDADAS:
• Verificar si el código de barras es correcto
• Revisar si el producto debe agregarse a la base de datos
{f"• Revisar los {len(resultados_google)} resultados de Google encontrados" if resultados_google else ""}
{f"• Usar la información de APIs para crear el registro" if info_producto['encontrado'] else ""}
• Considerar agregar el producto manualmente si es necesario

🔗 ENLACES RÁPIDOS:
• Agregar producto: http://192.168.1.101:8000/agregar_producto/
• Buscar en Jumbo: https://www.jumbo.cl/buscar?q={codigo_barras}
• Buscar en Google: https://www.google.cl/search?q={codigo_barras}+producto+chile

Este correo fue generado automáticamente por el sistema de lector de precios."""
        
        print(f"📧 [EMAIL] ✅ Mensaje preparado")
        
        # Verificar configuración
        from_email = getattr(settings, 'NOTIFICATION_FROM_EMAIL', None)
        admin_email = getattr(settings, 'ADMIN_EMAIL', None)
        
        if not from_email or not admin_email:
            print(f"❌ [EMAIL] Configuración incompleta - FROM: {from_email}, TO: {admin_email}")
            return False
        
        print(f"📧 [EMAIL] Enviando desde: {from_email}")
        print(f"📧 [EMAIL] Enviando hacia: {admin_email}")
        
        # Enviar correo
        resultado = send_mail(
            subject=f'🚫 Producto no encontrado - {codigo_barras} ({len(resultados_google)} resultados Google)',
            message=mensaje_texto,
            from_email=from_email,
            recipient_list=[admin_email],
            html_message=mensaje_html,
            fail_silently=False
        )
        
        if resultado:
            print(f"✅ [EMAIL] ===== CORREO ENVIADO EXITOSAMENTE =====")
            print(f"📧 [EMAIL] Código: {codigo_barras}")
            print(f"📧 [EMAIL] Google: {len(resultados_google)} resultados")
            print(f"📧 [EMAIL] APIs: {'✅' if info_producto['encontrado'] else '❌'}")
            print(f"📧 [EMAIL] Tiempo total: {tiempo_total}s")
        else:
            print(f"❌ [EMAIL] Error enviando correo para código: {codigo_barras}")
        
        return resultado
        
    except Exception as e:
        print(f"💥 [EMAIL] Error enviando correo para código {codigo_barras}: {e}")
        import traceback
        print(f"💥 [EMAIL] Traceback completo: {traceback.format_exc()}")
        return False


def test_busqueda_internet(request):
    """
    Test de búsqueda en internet
    """
    codigo = request.GET.get('codigo', '7802820005455')
    
    print(f"🧪 [TEST] Probando búsqueda internet para: {codigo}")
    
    try:
        resultado = buscar_producto_en_internet(codigo)
        
        return JsonResponse({
            'status': 'success',
            'codigo_buscado': codigo,
            'resultado': resultado,
            'encontrado': resultado['encontrado']
        })
        
    except Exception as e:
        print(f"❌ [TEST] Error: {e}")
        return JsonResponse({'error': str(e)})


def test_correo_completo(request):
    """
    Test completo: buscar + enviar correo
    """
    codigo = request.GET.get('codigo', '8445291792388')
    
    print(f"📧 [TEST-CORREO] Probando correo completo para: {codigo}")
    
    try:
        resultado = enviar_notificacion_producto_no_encontrado(codigo, '127.0.0.1')
        
        return JsonResponse({
            'status': 'success',
            'codigo': codigo,
            'correo_enviado': resultado,
            'message': 'Revisa tu correo y la consola'
        })
        
    except Exception as e:
        print(f"❌ [TEST-CORREO] Error: {e}")
        return JsonResponse({'error': str(e)})

def test_correo_con_google(request):
    """
    Test completo: buscar + Google + enviar correo
    """
    codigo = request.GET.get('codigo', '7802820005455')
    
    print(f"📧 [TEST-COMPLETO] ===== PROBANDO SISTEMA COMPLETO =====")
    print(f"📧 [TEST-COMPLETO] Código: {codigo}")
    
    try:
        # Probar búsqueda en Google directamente
        print(f"🔍 [TEST-COMPLETO] Probando búsqueda Google...")
        resultados_google, tiempo = buscar_resultados_google(codigo, max_resultados=3)
        
        # Simular envío de correo completo
        print(f"📧 [TEST-COMPLETO] Simulando envío de correo...")
        resultado_correo = enviar_notificacion_producto_no_encontrado(codigo, '127.0.0.1')
        
        return JsonResponse({
            'status': 'success',
            'codigo': codigo,
            'google_resultados': len(resultados_google),
            'google_tiempo': tiempo,
            'correo_enviado': resultado_correo,
            'primeros_resultados': [
                {
                    'title': r['title'][:100],
                    'link': r['link'],
                    'snippet': r['snippet'][:100]
                } for r in resultados_google[:2]
            ],
            'message': 'Revisa tu correo para ver el resultado completo'
        })
        
    except Exception as e:
        print(f"❌ [TEST-COMPLETO] Error: {e}")
        import traceback
        print(f"❌ [TEST-COMPLETO] Traceback: {traceback.format_exc()}")
        return JsonResponse({'error': str(e)})


def buscar_en_google_scraping(codigo_barras, max_resultados=5):
    """
    Buscar en Google con múltiples estrategias anti-detección
    """
    print(f"🔍 [GOOGLE-SCRAPING] Iniciando búsqueda para: {codigo_barras}")
    
    resultados = []
    
    try:
        # ESTRATEGIA 1: Headers más realistas y rotación de User-Agent
        user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0'
        ]
        
        import random
        
        for attempt in range(3):  # 3 intentos con diferentes estrategias
            try:
                print(f"🔍 [GOOGLE-SCRAPING] Intento {attempt + 1}/3")
                
                headers = {
                    'User-Agent': random.choice(user_agents),
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                    'Accept-Language': 'es-ES,es;q=0.9,en;q=0.8',
                    'Accept-Encoding': 'gzip, deflate, br',
                    'DNT': '1',
                    'Connection': 'keep-alive',
                    'Upgrade-Insecure-Requests': '1',
                    'Sec-Fetch-Dest': 'document',
                    'Sec-Fetch-Mode': 'navigate',
                    'Sec-Fetch-Site': 'none',
                    'Sec-Fetch-User': '?1',
                    'Cache-Control': 'max-age=0'
                }
                
                # ESTRATEGIA 2: Diferentes dominios y parámetros
                if attempt == 0:
                    # Intento 1: Google estándar
                    query = f'"{codigo_barras}"'
                    url = f"https://www.google.com/search?q={quote(query)}&hl=es&gl=cl"
                elif attempt == 1:
                    # Intento 2: Google con más parámetros
                    query = codigo_barras
                    url = f"https://www.google.com/search?q={quote(query)}&hl=es&gl=cl&num=20&start=0&safe=off"
                else:
                    # Intento 3: Búsqueda específica de productos
                    query = f"{codigo_barras} producto"
                    url = f"https://www.google.com/search?q={quote(query)}&hl=es&gl=cl&tbm="
                
                print(f"🔍 [GOOGLE-SCRAPING] Query: {query}")
                print(f"🔍 [GOOGLE-SCRAPING] URL: {url}")
                
                # ESTRATEGIA 3: Sesión con cookies
                session = requests.Session()
                session.headers.update(headers)
                
                # Simular una visita inicial a Google
                try:
                    session.get('https://www.google.com', timeout=10)
                    time.sleep(random.uniform(1, 3))
                except:
                    pass
                
                # Realizar la búsqueda
                response = session.get(url, timeout=15)
                print(f"🔍 [GOOGLE-SCRAPING] Status: {response.status_code}")
                
                if response.status_code == 200:
                    # Verificar si no estamos bloqueados
                    if 'blocked' in response.text.lower() or 'captcha' in response.text.lower():
                        print(f"🔍 [GOOGLE-SCRAPING] ⚠️ Posible bloqueo detectado en intento {attempt + 1}")
                        time.sleep(random.uniform(3, 6))
                        continue
                    
                    soup = BeautifulSoup(response.content, 'html.parser')
                    
                    # ESTRATEGIA 4: Múltiples selectores más específicos
                    resultados_encontrados = []
                    
                    # Selector 1: Resultados estándar
                    for div in soup.select('div.g'):
                        resultado = extraer_datos_resultado(div)
                        if resultado:
                            resultados_encontrados.append(resultado)
                    
                    # Selector 2: Resultados alternativos
                    if not resultados_encontrados:
                        for div in soup.select('div[data-ved]'):
                            resultado = extraer_datos_resultado(div)
                            if resultado:
                                resultados_encontrados.append(resultado)
                    
                    # Selector 3: Resultados de shopping/productos
                    if not resultados_encontrados:
                        for div in soup.select('.commercial-unit-desktop-top, .pla-unit'):
                            resultado = extraer_datos_resultado(div)
                            if resultado:
                                resultados_encontrados.append(resultado)
                    
                    print(f"🔍 [GOOGLE-SCRAPING] Encontrados {len(resultados_encontrados)} resultados en intento {attempt + 1}")
                    
                    if resultados_encontrados:
                        # Procesar y filtrar resultados
                        for resultado in resultados_encontrados[:max_resultados]:
                            if not any(r['link'] == resultado['link'] for r in resultados):
                                resultados.append(resultado)
                        
                        if len(resultados) >= max_resultados:
                            break
                    
                    # Pausa entre intentos
                    if attempt < 2:
                        time.sleep(random.uniform(2, 5))
                
                elif response.status_code == 429:
                    print(f"🔍 [GOOGLE-SCRAPING] ⚠️ Rate limit - esperando más tiempo...")
                    time.sleep(random.uniform(10, 20))
                else:
                    print(f"🔍 [GOOGLE-SCRAPING] ❌ Error HTTP {response.status_code}")
                    time.sleep(random.uniform(2, 4))
                    
            except Exception as e:
                print(f"🔍 [GOOGLE-SCRAPING] Error en intento {attempt + 1}: {e}")
                time.sleep(random.uniform(3, 6))
                continue
        
        # ESTRATEGIA 5: Búsquedas alternativas si no encontramos nada
        if not resultados:
            print(f"🔍 [GOOGLE-SCRAPING] Intentando búsquedas alternativas...")
            resultados_alternativos = buscar_sitios_especificos(codigo_barras)
            resultados.extend(resultados_alternativos)
        
        print(f"🔍 [GOOGLE-SCRAPING] ✅ TOTAL FINAL: {len(resultados)} resultados")
        
        return resultados
        
    except Exception as e:
        print(f"🔍 [GOOGLE-SCRAPING] ❌ ERROR GENERAL: {e}")
        return []

def extraer_datos_resultado(elemento):
    """
    Extrae datos de un elemento de resultado de Google
    """
    try:
        # Buscar título
        title_selectors = ['h3', '.LC20lb', '[role="heading"]', 'h3.LC20lb', '.DKV0Md', 'a h3']
        title = ""
        
        for selector in title_selectors:
            title_elem = elemento.select_one(selector)
            if title_elem:
                title = title_elem.get_text(strip=True)
                break
        
        if not title or len(title) < 3:
            return None
        
        # Buscar link
        link_elem = elemento.select_one('a[href]')
        if not link_elem:
            return None
        
        link = link_elem.get('href', '')
        
        # Limpiar links de Google
        if link.startswith('/url?'):
            try:
                from urllib.parse import parse_qs, urlparse
                parsed = urlparse(link)
                link = parse_qs(parsed.query).get('q', [link])[0]
            except:
                return None
        
        if not link.startswith('http'):
            return None
        
        # Buscar snippet
        snippet_selectors = [
            '.VwiC3b', '.s3v9rd', '.st', '.IsZvec', 
            '[data-content-feature="1"]', '.aCOpRe',
            'span[style*="color"]', '.yXK7lf', '.s'
        ]
        
        snippet = ""
        for selector in snippet_selectors:
            snippet_elem = elemento.select_one(selector)
            if snippet_elem:
                snippet = snippet_elem.get_text(strip=True)
                if snippet:
                    break
        
        # Extraer dominio
        try:
            from urllib.parse import urlparse
            parsed_url = urlparse(link)
            display_link = parsed_url.netloc.replace('www.', '')
        except:
            display_link = link[:50] + "..."
        
        # Detectar tiendas
        tiendas_conocidas = [
            'jumbo.cl', 'lider.cl', 'santaisabel.cl', 'tottus.cl',
            'unimarc.cl', 'ekono.cl', 'falabella.com', 'ripley.cl',
            'mercadolibre.', 'amazon.', 'ebay.', 'alibaba.'
        ]
        
        es_tienda = any(tienda in link.lower() for tienda in tiendas_conocidas)
        
        resultado = {
            'title': title,
            'link': link,
            'snippet': snippet[:300] + "..." if len(snippet) > 300 else snippet,
            'display_link': display_link,
            'query_used': "Google Search",
            'es_tienda': es_tienda,
            'imagen_url': "",  # Se puede implementar después
            'relevancia': 1
        }
        
        print(f"🔍 [EXTRAER] ✅ {display_link}: {title[:40]}...")
        return resultado
        
    except Exception as e:
        print(f"🔍 [EXTRAER] Error: {e}")
        return None

def buscar_sitios_especificos(codigo_barras):
    """
    Búsqueda directa en sitios específicos como respaldo
    """
    print(f"🔍 [SITIOS-ESPECIFICOS] Buscando en sitios conocidos...")
    
    resultados = []
    
    # Enlaces directos a sitios conocidos
    sitios = [
        {
            'nombre': 'Jumbo Chile',
            'url': f'https://www.jumbo.cl/buscar?q={codigo_barras}',
            'display': 'jumbo.cl',
            'es_tienda': True
        },
        {
            'nombre': 'Líder Chile', 
            'url': f'https://www.lider.cl/supermercado/search?q={codigo_barras}',
            'display': 'lider.cl',
            'es_tienda': True
        },
        {
            'nombre': 'Santa Isabel',
            'url': f'https://www.santaisabel.cl/buscar?q={codigo_barras}',
            'display': 'santaisabel.cl', 
            'es_tienda': True
        }
    ]
    
    for sitio in sitios:
        resultado = {
            'title': f"Buscar '{codigo_barras}' en {sitio['nombre']}",
            'link': sitio['url'],
            'snippet': f"Búsqueda directa del código de barras {codigo_barras} en {sitio['nombre']}",
            'display_link': sitio['display'],
            'query_used': "Búsqueda directa",
            'es_tienda': sitio['es_tienda'],
            'imagen_url': "",
            'relevancia': 2
        }
        resultados.append(resultado)
        print(f"🔍 [SITIOS-ESPECIFICOS] ✅ {sitio['nombre']}")
    
    return resultados

def buscar_resultados_google(codigo_barras, max_resultados=5):
    """
    Función principal para buscar en Google
    """
    print(f"🔍 [GOOGLE] ===== BÚSQUEDA EN GOOGLE INICIADA =====")
    print(f"🔍 [GOOGLE] Código: {codigo_barras}")
    
    tiempo_inicio = time.time()
    
    # Usar scraping como método principal
    resultados = buscar_en_google_scraping(codigo_barras, max_resultados)
    
    tiempo_total = round(time.time() - tiempo_inicio, 2)
    
    print(f"🔍 [GOOGLE] ✅ Búsqueda completada en {tiempo_total}s")
    print(f"🔍 [GOOGLE] Resultados encontrados: {len(resultados)}")
    
    return resultados, tiempo_total     


def test_google_simple(request):
    """
    Test específico para la búsqueda simplificada de Google
    """
    codigo = request.GET.get('codigo', '7802820005455')
    
    print(f"🔍 [TEST-GOOGLE-SIMPLE] ===== PROBANDO BÚSQUEDA SIMPLIFICADA =====")
    print(f"🔍 [TEST-GOOGLE-SIMPLE] Código: {codigo}")
    
    try:
        # Probar solo la búsqueda de Google
        resultados_google, tiempo = buscar_resultados_google(codigo, max_resultados=6)
        
        # Analizar tipos de resultados
        tiendas = [r for r in resultados_google if r.get('es_tienda', False)]
        otros = [r for r in resultados_google if not r.get('es_tienda', False)]
        
        return JsonResponse({
            'status': 'success',
            'codigo': codigo,
            'total_resultados': len(resultados_google),
            'tiendas_encontradas': len(tiendas),
            'otros_sitios': len(otros),
            'tiempo_busqueda': tiempo,
            'queries_usadas': [
                f'"{codigo}"',
                f'{codigo}',
                f'"{codigo}" producto'
            ],
            'resultados_detalle': [
                {
                    'titulo': r['title'][:80],
                    'sitio': r['display_link'],
                    'es_tienda': r.get('es_tienda', False),
                    'query': r['query_used'],
                    'snippet': r['snippet'][:100] + "..." if len(r['snippet']) > 100 else r['snippet']
                } for r in resultados_google
            ],
            'message': f'Búsqueda completada. {len(tiendas)} tiendas y {len(otros)} otros sitios encontrados.'
        }, json_dumps_params={'ensure_ascii': False, 'indent': 2})
        
    except Exception as e:
        print(f"❌ [TEST-GOOGLE-SIMPLE] Error: {e}")
        import traceback
        print(f"❌ [TEST-GOOGLE-SIMPLE] Traceback: {traceback.format_exc()}")
        return JsonResponse({'error': str(e)})


def buscar_con_duckduckgo(codigo_barras, max_resultados=3):
    """
    Búsqueda alternativa usando DuckDuckGo (menos restricciones)
    """
    try:
        print(f"🔍 [DUCKDUCKGO] Búsqueda alternativa: {codigo_barras}")
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        url = f"https://duckduckgo.com/html?q={quote(codigo_barras)}"
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')
            resultados = []
            
            for result in soup.select('.result')[:max_resultados]:
                try:
                    title_elem = result.select_one('.result__title a')
                    if not title_elem:
                        continue
                    
                    title = title_elem.get_text(strip=True)
                    link = title_elem.get('href', '')
                    
                    snippet_elem = result.select_one('.result__snippet')
                    snippet = snippet_elem.get_text(strip=True) if snippet_elem else ""
                    
                    if title and link.startswith('http'):
                        resultados.append({
                            'title': title,
                            'link': link,
                            'snippet': snippet,
                            'display_link': urlparse(link).netloc.replace('www.', ''),
                            'query_used': "DuckDuckGo",
                            'es_tienda': any(t in link.lower() for t in ['jumbo', 'lider', 'mercado']),
                            'imagen_url': "",
                            'relevancia': 3
                        })
                        print(f"🔍 [DUCKDUCKGO] ✅ {title[:40]}...")
                except:
                    continue
            
            return resultados
        
    except Exception as e:
        print(f"🔍 [DUCKDUCKGO] Error: {e}")
    
    return []



    

#from django.http import JsonResponse
#from django.shortcuts import render, redirect, get_object_or_404
#from django.contrib import messages
#from .models import Producto, ImagenPromocion
#from .forms import ProductoForm
#import re
#import csv
#from django.http import HttpResponse
#from django.contrib.admin.views.decorators import staff_member_required
## COMENTAR TEMPORALMENTE:
##import requests
##from bs4 import BeautifulSoup
#import json
#import time
#import threading
#from django.core.mail import send_mail
#from django.template.loader import render_to_string
#from django.conf import settings
#from datetime import datetime
#
#
#def limpiar_codigo_barras(codigo):
#    # Elimina espacios, tabulaciones, saltos de línea y retornos de carro
#    return re.sub(r'[\s\r\n\t]+', '', codigo)
#
#
#def buscar_producto(request):
#    codigo = request.GET.get('codigo_barras', '')
#    codigo_original = codigo
#    codigo = limpiar_codigo_barras(codigo)
#    print(f"Código recibido en backend (limpio): '{codigo}'")
#
#    # Obtener IP del cliente para el reporte
#    ip_cliente = request.META.get('HTTP_X_FORWARDED_FOR')
#    if ip_cliente:
#        ip_cliente = ip_cliente.split(',')[0]
#    else:
#        ip_cliente = request.META.get('REMOTE_ADDR', 'No disponible')
#
#    # Verificar si se solicita búsqueda exacta
#    busqueda_exacta = request.GET.get('busqueda_exacta') == 'true'
#    exacto = request.GET.get('exacto') == '1'
#    no_similar = request.GET.get('no_similar') == '1'
#
#    if not codigo:
#        return JsonResponse({'error': 'Código de barras no proporcionado'}, status=400)
#    if len(codigo) > 14:
#        return JsonResponse({'error': 'Código de barras demasiado largo'}, status=400)
#    
#    try:
#        # Paso 1: Intentar búsqueda exacta primero
#        producto = Producto.objects.filter(codigo_barras=codigo).first()
#        
#        # Si se solicita SOLO búsqueda exacta, no hacer búsquedas adicionales
#        if busqueda_exacta and exacto and no_similar:
#            # Solo intentar con/sin cero inicial para códigos que empiezan con 0
#            if not producto and codigo.startswith('0'):
#                sin_ceros = codigo.lstrip('0')
#                if sin_ceros:  # Asegurar que no quede vacío
#                    producto = Producto.objects.filter(codigo_barras=sin_ceros).first()
#                    if producto:
#                        print(f"Encontrado sin cero inicial: {producto.codigo_barras}")
#            
#            # También intentar agregando un cero si no se encontró
#            if not producto and not codigo.startswith('0'):
#                codigo_con_cero = '0' + codigo
#                producto = Producto.objects.filter(codigo_barras=codigo_con_cero).first()
#                if producto:
#                    print(f"Encontrado con cero inicial: {producto.codigo_barras}")
#        else:
#            # Lógica de búsqueda flexible original (solo si NO es búsqueda exacta)
#            if not producto:
#                # Intentar sin ceros iniciales (si comienza con 0)
#                if codigo.startswith('0'):
#                    sin_ceros = codigo.lstrip('0')
#                    if sin_ceros:  # Asegurar que no quede vacío
#                        producto = Producto.objects.filter(codigo_barras=sin_ceros).first()
#                else:
#                    # Intentar añadiendo ceros iniciales (hasta 13 o 14 dígitos)
#                    for i in range(1, 5):  # Probar añadiendo de 1 a 4 ceros
#                        codigo_con_ceros = '0' * i + codigo
#                        if len(codigo_con_ceros) in (13, 14):  # Si llegamos a 13 o 14 dígitos
#                            producto = Producto.objects.filter(codigo_barras=codigo_con_ceros).first()
#                            if producto:
#                                break
#            
#            # Paso 3: Si todavía no hay coincidencia, buscar en toda la base de datos por similitud
#            if not producto:
#                # Verificar en la base de datos por coincidencias con los mismos dígitos sin importar el orden
#                todos_productos = Producto.objects.all()
#                for p in todos_productos:
#                    # Si los mismos dígitos están presentes (sin importar orden)
#                    if len(p.codigo_barras) == len(codigo) and sorted(p.codigo_barras) == sorted(codigo):
#                        producto = p
#                        print(f"Coincidencia por dígitos similares: {p.codigo_barras}")
#                        break
#                    
#                    # Probar con código con o sin ceros iniciales
#                    codigo_db_sin_ceros = p.codigo_barras.lstrip('0')
#                    codigo_scan_sin_ceros = codigo.lstrip('0')
#                    
#                    if codigo_db_sin_ceros == codigo_scan_sin_ceros:
#                        producto = p
#                        print(f"Coincidencia sin ceros iniciales: {p.codigo_barras}")
#                        break
#                    
#                    # Verificar si los códigos contienen los mismos dígitos (posible inversión)
#                    # Por ejemplo, 417890039120 vs 041789003912
#                    if len(codigo_db_sin_ceros) == len(codigo_scan_sin_ceros) and set(codigo_db_sin_ceros) == set(codigo_scan_sin_ceros):
#                        # Si hay al menos 60% de coincidencia posicional
#                        coincidencias = sum(1 for a, b in zip(codigo_db_sin_ceros, codigo_scan_sin_ceros) if a == b)
#                        if coincidencias / len(codigo_db_sin_ceros) >= 0.6:
#                            producto = p
#                            print(f"Posible inversión/desorden detectada: {codigo} vs {p.codigo_barras}")
#                            break
#        
#        if producto:
#            print(f"✅ Producto encontrado: {producto.nombre} con código {producto.codigo_barras}")
#            return JsonResponse({
#                'nombre': producto.nombre,
#                'precio': str(producto.precio),
#                'sku': producto.sku or '',
#                'codigo_barras': producto.codigo_barras,
#                'codigo_original': codigo_original,
#                'precio_vecino': str(producto.precio_vecino) if producto.precio_vecino else None
#            })
#        
#        # Si llegamos aquí, no se encontró el producto
#        print(f"❌ PRODUCTO NO ENCONTRADO para código: {codigo}")
#        
#        # Enviar correo de notificación en un hilo separado
#        def enviar_correo_async():
#            try:
#                print(f"📧 [CORREO] Iniciando envío para código: {codigo}")
#                print(f"📧 [CORREO] IP cliente: {ip_cliente}")
#                print(f"📧 [CORREO] Email configurado: {getattr(settings, 'EMAIL_HOST_USER', 'NO CONFIGURADO')}")
#                print(f"📧 [CORREO] Admin email: {getattr(settings, 'ADMIN_EMAIL', 'NO CONFIGURADO')}")
#                
#                resultado = enviar_notificacion_producto_no_encontrado(codigo, ip_cliente)
#                
#                if resultado:
#                    print(f"✅ [CORREO] Envío exitoso")
#                else:
#                    print(f"❌ [CORREO] Error en envío")
#                    
#            except Exception as e:
#                print(f"💥 [CORREO] Excepción: {e}")
#                import traceback
#                print(f"💥 [CORREO] Traceback: {traceback.format_exc()}")
#        
#        # Ejecutar en segundo plano para no bloquear la respuesta
#        hilo_correo = threading.Thread(target=enviar_correo_async)
#        hilo_correo.daemon = True
#        hilo_correo.start()
#        print(f"🚀 Hilo de correo iniciado en segundo plano")
#        
#        return JsonResponse({
#            'error': 'Producto no encontrado',
#            'codigo_escaneado': codigo
#        }, status=404)
#        
#    except Exception as e:
#        print('💥 Error en buscar_producto:', str(e))
#        return JsonResponse({'error': 'Error interno: ' + str(e)}, status=500)
#
#
#def lector_precios(request):
#    productos = Producto.objects.all()
#    imagenes_promociones = ImagenPromocion.objects.all()
#    return render(request, 'elFaro/lector_precios.html', {
#        'productos': productos,
#        'imagenes_promociones': imagenes_promociones,
#    })
#
#
#def mantenedor_promociones(request):
#    if request.method == 'POST':
#        if 'eliminar_id' in request.POST:
#            ImagenPromocion.objects.filter(id=request.POST['eliminar_id']).delete()
#        elif 'imagen' in request.FILES:
#            ImagenPromocion.objects.create(
#                imagen=request.FILES['imagen'],
#                nombre=request.POST.get('nombre', '')
#            )
#        return redirect('mantenedor_promociones')
#    imagenes = ImagenPromocion.objects.all()
#    return render(request, 'elFaro/mantenedor_promociones.html', {'imagenes': imagenes})
#
#
#def agregar_producto(request):
#    if request.method == 'POST':
#        form = ProductoForm(request.POST)
#        if form.is_valid():
#            form.save()
#            messages.success(request, 'Producto agregado correctamente.')
#            return redirect('agregar_producto')
#    else:
#        form = ProductoForm()
#    return render(request, 'elFaro/agregar_producto.html', {'form': form})
#
#
#def lista_productos(request):
#    productos = Producto.objects.all()
#    return render(request, 'elFaro/lista_productos.html', {'productos': productos})
#
#
#def editar_producto(request, producto_id):
#    producto = get_object_or_404(Producto, id=producto_id)
#    if request.method == 'POST':
#        form = ProductoForm(request.POST, instance=producto)
#        if form.is_valid():
#            form.save()
#            return redirect('lista_productos')
#    else:
#        form = ProductoForm(instance=producto)
#    return render(request, 'elFaro/editar_producto.html', {'form': form, 'producto': producto})
#
#
#def eliminar_producto(request, producto_id):
#    producto = get_object_or_404(Producto, id=producto_id)
#    if request.method == 'POST':
#        producto.delete()
#        return redirect('lista_productos')
#    return redirect('lista_productos')
#
#
#@staff_member_required
#def export_productos_csv(request):
#    response = HttpResponse(content_type='text/csv')
#    response['Content-Disposition'] = 'attachment; filename="productos.csv"'
#    
#    # Crear el escritor CSV
#    writer = csv.writer(response)
#    
#    # Escribir encabezados
#    writer.writerow(['codigo_barras', 'nombre', 'precio', 'precio_vecino', 'sku'])
#    
#    # Escribir datos de productos
#    productos = Producto.objects.all()
#    for producto in productos:
#        # Convertir None a cadena vacía para evitar errores en CSV
#        precio_vecino = producto.precio_vecino if producto.precio_vecino else ''
#        sku = producto.sku if producto.sku else ''
#        
#        writer.writerow([
#            producto.codigo_barras,
#            producto.nombre,
#            producto.precio,
#            precio_vecino,
#            sku
#        ])
#    
#    return response
#
#
#def test_email(request):
#    """
#    Función temporal para probar el envío de correo
#    """
#    try:
#        print(f"📧 [TEST] Probando configuración de correo...")
#        print(f"📧 [TEST] EMAIL_HOST_USER: {getattr(settings, 'EMAIL_HOST_USER', 'NO CONFIGURADO')}")
#        print(f"📧 [TEST] ADMIN_EMAIL: {getattr(settings, 'ADMIN_EMAIL', 'NO CONFIGURADO')}")
#        
#        resultado = send_mail(
#            subject='🧪 Prueba de correo - El Faro',
#            message='Este es un correo de prueba para verificar la configuración.',
#            from_email=getattr(settings, 'NOTIFICATION_FROM_EMAIL', 'no-configurado@test.com'),
#            recipient_list=[getattr(settings, 'ADMIN_EMAIL', 'admin@test.com')],
#            fail_silently=False
#        )
#        
#        if resultado:
#            print(f"✅ [TEST] Correo de prueba enviado exitosamente")
#            return JsonResponse({'status': 'success', 'message': 'Correo enviado exitosamente'})
#        else:
#            print(f"❌ [TEST] Error enviando correo de prueba")
#            return JsonResponse({'status': 'error', 'message': 'Error enviando correo'})
#            
#    except Exception as e:
#        print(f"💥 [TEST] Error en prueba de correo: {e}")
#        return JsonResponse({'status': 'error', 'message': f'Error: {str(e)}'})
#
#
## Reemplazar COMPLETAMENTE la función buscar_producto_en_internet con esta versión:
#
#def buscar_producto_en_internet(codigo_barras):
#    """
#    Busca información del producto - VERSIÓN SIMPLIFICADA Y EFECTIVA
#    """
#    print(f"🔍 [INTERNET] ===== BÚSQUEDA SIMPLIFICADA para: {codigo_barras} =====")
#    
#    resultados = {
#        'encontrado': False,
#        'nombre': '',
#        'descripcion': '',
#        'marca': '',
#        'categoria': '',
#        'fuente': '',
#        'imagen_url': '',
#        'precio_referencia': '',
#        'link_producto': ''
#    }
#    
#    headers = {
#        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
#        'Accept-Language': 'es-CL,es;q=0.9,en;q=0.8',
#        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
#    }
#    
#    # ===== FUENTE 1: Open Food Facts (MÁS CONFIABLE) =====
#    try:
#        print(f"🌐 [1] OPEN FOOD FACTS - Código: {codigo_barras}")
#        
#        url = f"https://world.openfoodfacts.org/api/v0/product/{codigo_barras}.json"
#        response = requests.get(url, timeout=15)
#        print(f"📊 [1] Status HTTP: {response.status_code}")
#        
#        if response.status_code == 200:
#            data = response.json()
#            print(f"📊 [1] Status en respuesta: {data.get('status')}")
#            
#            if data.get('status') == 1:
#                producto = data.get('product', {})
#                
#                # Buscar nombre en múltiples idiomas
#                nombres_posibles = [
#                    producto.get('product_name_es', ''),
#                    producto.get('product_name', ''),
#                    producto.get('product_name_en', ''),
#                    producto.get('abbreviated_product_name', ''),
#                    producto.get('generic_name_es', ''),
#                    producto.get('generic_name', '')
#                ]
#                
#                nombre = ''
#                for n in nombres_posibles:
#                    if n and len(n.strip()) > 3:
#                        nombre = n.strip()
#                        break
#                
#                if nombre:
#                    # Construir link de búsqueda en sitios chilenos
#                    nombre_para_busqueda = nombre.replace(' ', '+')
#                    links_sugeridos = [
#                        f"https://www.jumbo.cl/buscar?q={nombre_para_busqueda}",
#                        f"https://www.lider.cl/supermercado/search?q={nombre_para_busqueda}",
#                        f"https://www.google.cl/search?q={nombre_para_busqueda}+chile"
#                    ]
#                    
#                    resultados.update({
#                        'encontrado': True,
#                        'nombre': nombre,
#                        'descripcion': producto.get('generic_name_es', '') or producto.get('generic_name', ''),
#                        'marca': producto.get('brands', ''),
#                        'categoria': producto.get('categories_tags', [])[:3] if producto.get('categories_tags') else producto.get('categories', ''),
#                        'imagen_url': producto.get('image_url', '') or producto.get('image_front_url', ''),
#                        'link_producto': links_sugeridos[0],  # Link a Jumbo por defecto
#                        'precio_referencia': 'Consultar en tienda',
#                        'fuente': 'Open Food Facts + Enlaces Chile'
#                    })
#                    
#                    print(f"✅ [1] ===== ENCONTRADO EN OPEN FOOD FACTS =====")
#                    print(f"📦 [1] Nombre: {nombre}")
#                    print(f"🏷️ [1] Marca: {resultados['marca']}")
#                    print(f"🔗 [1] Link sugerido: {resultados['link_producto']}")
#                    return resultados
#            
#            print(f"❌ [1] Open Food Facts: producto no encontrado (status={data.get('status')})")
#        else:
#            print(f"❌ [1] Open Food Facts: Error HTTP {response.status_code}")
#    
#    except Exception as e:
#        print(f"❌ [1] Error en Open Food Facts: {e}")
#    
#    # ===== FUENTE 2: UPC Database =====
#    try:
#        print(f"🔍 [2] UPC DATABASE - Código: {codigo_barras}")
#        
#        url = f"https://api.upcitemdb.com/prod/trial/lookup?upc={codigo_barras}"
#        response = requests.get(url, timeout=10)
#        print(f"📊 [2] Status HTTP: {response.status_code}")
#        
#        if response.status_code == 200:
#            data = response.json()
#            print(f"📊 [2] Response code: {data.get('code')}")
#            
#            if data.get('code') == 'OK' and data.get('items'):
#                item = data['items'][0]
#                nombre = item.get('title', '')
#                
#                if nombre and len(nombre) > 3:
#                    # Crear links de búsqueda para sitios chilenos
#                    nombre_para_busqueda = nombre.replace(' ', '+')
#                    link_jumbo = f"https://www.jumbo.cl/buscar?q={nombre_para_busqueda}"
#                    
#                    resultados.update({
#                        'encontrado': True,
#                        'nombre': nombre,
#                        'descripcion': item.get('description', ''),
#                        'marca': item.get('brand', ''),
#                        'categoria': item.get('category', ''),
#                        'imagen_url': item.get('images', [''])[0] if item.get('images') else '',
#                        'link_producto': link_jumbo,
#                        'precio_referencia': 'Consultar en tienda',
#                        'fuente': 'UPC Database + Enlaces Chile'
#                    })
#                    
#                    print(f"✅ [2] ===== ENCONTRADO EN UPC DATABASE =====")
#                    print(f"📦 [2] Nombre: {nombre}")
#                    print(f"🔗 [2] Link sugerido: {link_jumbo}")
#                    return resultados
#            
#            print(f"❌ [2] UPC Database: no encontrado o sin items")
#        else:
#            print(f"❌ [2] UPC Database: Error HTTP {response.status_code}")
#    
#    except Exception as e:
#        print(f"❌ [2] Error en UPC Database: {e}")
#    
#    # ===== FUENTE 3: Búsqueda Simple en Google =====
#    try:
#        print(f"🔍 [3] GOOGLE SIMPLE - Código: {codigo_barras}")
#        
#        # Búsqueda básica por código de barras
#        query = f'"{codigo_barras}" producto'
#        url_google = f"https://www.google.com/search?q={query}&hl=es"
#        
#        response = requests.get(url_google, headers=headers, timeout=15)
#        print(f"📊 [3] Status HTTP Google: {response.status_code}")
#        
#        if response.status_code == 200:
#            soup = BeautifulSoup(response.content, 'html.parser')
#            
#            # Buscar títulos en resultados de Google
#            titulos = soup.select('h3')
#            
#            for titulo in titulos[:5]:
#                texto = titulo.get_text(strip=True)
#                if texto and len(texto) > 10 and codigo_barras not in texto.lower():
#                    # Limpiar el título
#                    nombre = texto.split('|')[0].split('-')[0].strip()
#                    
#                    if len(nombre) > 5:
#                        # Crear link de búsqueda
#                        nombre_para_busqueda = nombre.replace(' ', '+')
#                        link_busqueda = f"https://www.jumbo.cl/buscar?q={nombre_para_busqueda}"
#                        
#                        resultados.update({
#                            'encontrado': True,
#                            'nombre': nombre,
#                            'link_producto': link_busqueda,
#                            'precio_referencia': 'Consultar en tienda',
#                            'fuente': 'Google + Enlaces Chile'
#                        })
#                        
#                        print(f"✅ [3] ===== ENCONTRADO EN GOOGLE =====")
#                        print(f"📦 [3] Nombre: {nombre}")
#                        print(f"🔗 [3] Link: {link_busqueda}")
#                        return resultados
#            
#            print(f"❌ [3] Google: no se encontraron nombres válidos")
#        else:
#            print(f"❌ [3] Google: Error HTTP {response.status_code}")
#    
#    except Exception as e:
#        print(f"❌ [3] Error en Google: {e}")
#    
#    # ===== FUENTE 4: Crear enlace de búsqueda manual =====
#    print(f"🔗 [4] CREANDO ENLACES DE BÚSQUEDA MANUAL")
#    
#    # Si no encontramos nada, al menos dar enlaces para buscar manualmente
#    resultados.update({
#        'encontrado': True,  # Consideramos "encontrado" porque damos enlaces útiles
#        'nombre': f'Producto con código {codigo_barras}',
#        'descripcion': 'Código de barras detectado - buscar manualmente',
#        'link_producto': f"https://www.jumbo.cl/buscar?q={codigo_barras}",
#        'precio_referencia': 'Buscar en tienda',
#        'fuente': 'Enlaces de búsqueda manual'
#    })
#    
#    print(f"✅ [4] ===== ENLACES MANUALES CREADOS =====")
#    print(f"📦 [4] Descripción: {resultados['descripcion']}")
#    print(f"🔗 [4] Link: {resultados['link_producto']}")
#    
#    return resultados
#
#
#def enviar_notificacion_producto_no_encontrado(codigo_barras, ip_cliente=None):
#    """
#    Envía correo cuando no se encuentra un producto y busca sugerencias en internet
#    """
#    try:
#        print(f"📧 [EMAIL] Iniciando proceso de envío para código: {codigo_barras}")
#        
#        # Buscar información del producto en internet
#        print(f"🔍 [EMAIL] Buscando información en internet...")
#        info_producto = buscar_producto_en_internet(codigo_barras)
#        
#        # Datos para el correo
#        contexto = {
#            'codigo_barras': codigo_barras,
#            'fecha_hora': datetime.now().strftime('%d/%m/%Y %H:%M:%S'),
#            'ip_cliente': ip_cliente or 'No disponible',
#            'producto_sugerido': info_producto,
#            'encontrado_en_internet': info_producto['encontrado']
#        }
#        
#        # Log del resultado de la búsqueda
#        print(f"📧 [EMAIL] Contexto preparado. Encontrado en internet: {info_producto['encontrado']}")
#        if info_producto['encontrado']:
#            print(f"📧 [EMAIL] Producto encontrado: {info_producto['nombre']} - Fuente: {info_producto['fuente']}")
#        else:
#            print(f"📧 [EMAIL] No se encontró información en internet")
#        
#        # Renderizar el template del correo
#        mensaje_html = None
#        try:
#            mensaje_html = render_to_string('elFaro/email_producto_no_encontrado.html', contexto)
#            print(f"📧 [EMAIL] Template HTML renderizado correctamente")
#        except Exception as template_error:
#            print(f"⚠️ [EMAIL] Error renderizando template HTML: {template_error}")
#        
#        # Crear mensaje de texto dinámico
#        if info_producto['encontrado']:
#            seccion_internet = f"""✅ SUGERENCIA ENCONTRADA EN INTERNET:
#
#📦 Nombre: {info_producto['nombre']}
#{f"🏷️ Marca: {info_producto['marca']}" if info_producto['marca'] else ""}
#{f"📝 Descripción: {info_producto['descripcion']}" if info_producto['descripcion'] else ""}
#{f"🗂️ Categoría: {info_producto['categoria']}" if info_producto['categoria'] else ""}
#{f"💰 Precio referencia: {info_producto['precio_referencia']}" if info_producto['precio_referencia'] else ""}
#{f"🔗 Link del producto: {info_producto['link_producto']}" if info_producto['link_producto'] else ""}
#🔗 Fuente: {info_producto['fuente']}"""
#        else:
#            seccion_internet = "⚠️ NO SE ENCONTRÓ INFORMACIÓN EN INTERNET"
#
#        mensaje_texto = f"""PRODUCTO NO ENCONTRADO - El Faro Algarrobo
#
#Se ha buscado un producto que no existe en la base de datos:
#
#📊 Código de barras: {codigo_barras}
#🕐 Fecha y hora: {contexto['fecha_hora']}
#🌐 IP del cliente: {contexto['ip_cliente']}
#
#{seccion_internet}
#
#💡 ACCIONES RECOMENDADAS:
#• Verificar si el producto debe agregarse a la base de datos
#• Revisar si el código de barras es correcto
#• Considerar agregar el producto manualmente si es necesario
#{f"• Usar la información sugerida para crear el registro del producto" if info_producto['encontrado'] else ""}
#{f"• Visitar el link proporcionado para ver más detalles del producto" if info_producto['encontrado'] and info_producto['link_producto'] else ""}
#
#Este correo fue generado automáticamente por el sistema de lector de precios."""
#        
#        print(f"📧 [EMAIL] Mensaje de texto preparado")
#        
#        # Verificar configuración
#        from_email = getattr(settings, 'NOTIFICATION_FROM_EMAIL', None)
#        admin_email = getattr(settings, 'ADMIN_EMAIL', None)
#        
#        if not from_email or not admin_email:
#            print(f"❌ [EMAIL] Configuración incompleta - FROM: {from_email}, TO: {admin_email}")
#            return False
#        
#        print(f"📧 [EMAIL] Enviando desde: {from_email}")
#        print(f"📧 [EMAIL] Enviando hacia: {admin_email}")
#        
#        # Enviar correo
#        resultado = send_mail(
#            subject=f'🚫 Producto no encontrado - Código: {codigo_barras}',
#            message=mensaje_texto,
#            from_email=from_email,
#            recipient_list=[admin_email],
#            html_message=mensaje_html,
#            fail_silently=False
#        )
#        
#        if resultado:
#            print(f"✅ [EMAIL] Correo enviado exitosamente para código: {codigo_barras}")
#            if info_producto['encontrado']:
#                print(f"📦 [EMAIL] Sugerencia incluida: {info_producto['nombre']} ({info_producto['fuente']})")
#                if info_producto['link_producto']:
#                    print(f"🔗 [EMAIL] Link incluido: {info_producto['link_producto']}")
#            else:
#                print("❌ [EMAIL] No se encontró información en internet para incluir")
#        else:
#            print(f"❌ [EMAIL] Error enviando correo para código: {codigo_barras}")
#        
#        return resultado
#        
#    except Exception as e:
#        print(f"💥 [EMAIL] Error enviando correo para código {codigo_barras}: {e}")
#        import traceback
#        print(f"💥 [EMAIL] Traceback completo: {traceback.format_exc()}")
#        return False
#
#def test_busqueda_internet(request):
#    """
#    Función de prueba ESPECÍFICA para debug de búsqueda en internet
#    """
#    codigo = request.GET.get('codigo', '7802820005455')  # Código de Coca Cola por defecto
#    
#    print(f"🧪 [TEST] ===== INICIANDO PRUEBA BÚSQUEDA INTERNET =====")
#    print(f"🧪 [TEST] Código a buscar: {codigo}")
#    
#    # Verificar que requests funciona
#    try:
#        import requests
#        print(f"✅ [TEST] Requests importado correctamente")
#        
#        # Prueba básica de internet
#        test_response = requests.get('https://www.google.com', timeout=5)
#        print(f"✅ [TEST] Conexión a internet OK (Google status: {test_response.status_code})")
#        
#    except Exception as e:
#        print(f"❌ [TEST] Error con requests o internet: {e}")
#        return JsonResponse({'error': f'Error con requests: {e}'})
#    
#    # Probar función de búsqueda
#    try:
#        resultado = buscar_producto_en_internet(codigo)
#        print(f"🧪 [TEST] Resultado búsqueda: {resultado}")
#        
#        return JsonResponse({
#            'status': 'success',
#            'codigo_buscado': codigo,
#            'resultado': resultado,
#            'encontrado': resultado['encontrado']
#        })
#        
#    except Exception as e:
#        print(f"❌ [TEST] Error en búsqueda: {e}")
#        import traceback
#        print(f"❌ [TEST] Traceback: {traceback.format_exc()}")
#        return JsonResponse({'error': f'Error en búsqueda: {e}'})
#
#def test_correo_completo(request):
#    """
#    Test completo: buscar + enviar correo
#    """
#    codigo = request.GET.get('codigo', '8445291792388')
#    
#    print(f"📧 [TEST-CORREO] ===== PROBANDO CORREO COMPLETO =====")
#    
#    # Simular envío de correo
#    try:
#        resultado = enviar_notificacion_producto_no_encontrado(codigo, '127.0.0.1')
#        
#        return JsonResponse({
#            'status': 'success',
#            'codigo': codigo,
#            'correo_enviado': resultado,
#            'message': 'Revisa tu correo y la consola para ver los logs'
#        })
#        
#    except Exception as e:
#        print(f"❌ [TEST-CORREO] Error: {e}")
#        return JsonResponse({'error': str(e)})
#
##def scrape_jumbo_cl(codigo_barras):
##    """
##    Scraping específico para Jumbo.cl - SOLO PARA APRENDIZAJE
##    """
##    print(f"🛒 [JUMBO-SCRAPER] ===== INICIANDO SCRAPING JUMBO.CL =====")
##    print(f"🛒 [JUMBO-SCRAPER] Código: {codigo_barras}")
##    
##    # Headers específicos para Jumbo
##    headers = {
##        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
##        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
##        'Accept-Language': 'es-CL,es;q=0.9,en;q=0.8',
##        'Accept-Encoding': 'gzip, deflate, br',
##        'DNT': '1',
##        'Connection': 'keep-alive',
##        'Upgrade-Insecure-Requests': '1',
##        'Sec-Fetch-Dest': 'document',
##        'Sec-Fetch-Mode': 'navigate',
##        'Sec-Fetch-Site': 'none',
##        'Cache-Control': 'max-age=0'
##    }
##    
##    resultado = {
##        'encontrado': False,
##        'nombre': '',
##        'precio': '',
##        'imagen_url': '',
##        'link_producto': '',
##        'descripcion': '',
##        'disponible': False
##    }
##    
##    try:
##        # Múltiples estrategias de búsqueda en Jumbo
##        urls_busqueda = [
##            f"https://www.jumbo.cl/buscar?q={codigo_barras}",
##            f"https://www.jumbo.cl/search?q={codigo_barras}",
##            f"https://www.jumbo.cl/productos?q={codigo_barras}"
##        ]
##        
##        for url in urls_busqueda:
##            try:
##                print(f"🛒 [JUMBO-SCRAPER] Probando URL: {url}")
##                
##                # Crear sesión para mantener cookies
##                session = requests.Session()
##                session.headers.update(headers)
##                
##                response = session.get(url, timeout=20)
##                print(f"📊 [JUMBO-SCRAPER] Status HTTP: {response.status_code}")
##                
##                if response.status_code == 200:
##                    soup = BeautifulSoup(response.content, 'html.parser')
##                    
##                    # Guardar HTML para análisis (debug)
##                    with open(f'debug_jumbo_{codigo_barras}.html', 'w', encoding='utf-8') as f:
##                        f.write(str(soup.prettify()))
##                    print(f"🛒 [JUMBO-SCRAPER] HTML guardado en debug_jumbo_{codigo_barras}.html")
##                    
##                    # Múltiples selectores para productos en Jumbo
##                    selectores_producto = [
##                        '.product-item',
##                        '.product-card', 
##                        '.shelf-product',
##                        '[data-testid*="product"]',
##                        '.product',
##                        '.item-product',
##                        '.vtex-product-summary',
##                        '.vtex-store-components',
##                        '[class*="product"]',
##                        '[class*="item"]'
##                    ]
##                    
##                    productos_encontrados = []
##                    
##                    for selector in selectores_producto:
##                        productos = soup.select(selector)
##                        if productos:
##                            print(f"🛒 [JUMBO-SCRAPER] Encontrado {len(productos)} elementos con selector: {selector}")
##                            productos_encontrados = productos[:5]  # Solo primeros 5
##                            break
##                    
##                    if not productos_encontrados:
##                        # Buscar elementos genéricos que puedan contener productos
##                        print(f"🛒 [JUMBO-SCRAPER] Buscando elementos genéricos...")
##                        productos_encontrados = soup.select('div[class*="product"], article, .card, [data-qa*="product"]')[:5]
##                    
##                    print(f"🛒 [JUMBO-SCRAPER] Total productos para analizar: {len(productos_encontrados)}")
##                    
##                    for i, producto in enumerate(productos_encontrados):
##                        print(f"🛒 [JUMBO-SCRAPER] --- Analizando producto {i+1} ---")
##                        
##                        # Buscar nombre del producto
##                        selectores_nombre = [
##                            '.product-name',
##                            '.product-title', 
##                            'h1', 'h2', 'h3', 'h4',
##                            '[data-testid*="name"]',
##                            '[data-testid*="title"]',
##                            '.title',
##                            '.name',
##                            '[class*="name"]',
##                            '[class*="title"]',
##                            'a[title]'
##                        ]
##                        
##                        nombre = ''
##                        for selector_nombre in selectores_nombre:
##                            elementos_nombre = producto.select(selector_nombre)
##                            for elem in elementos_nombre:
##                                texto = elem.get_text(strip=True) if elem.get_text else elem.get('title', '').strip()
##                                if texto and len(texto) > 3 and codigo_barras not in texto:
##                                    nombre = texto
##                                    print(f"🛒 [JUMBO-SCRAPER] Nombre encontrado: {nombre}")
##                                    break
##                            if nombre:
##                                break
##                        
##                        if not nombre:
##                            print(f"🛒 [JUMBO-SCRAPER] No se encontró nombre válido en producto {i+1}")
##                            continue
##                        
##                        # Buscar precio
##                        selectores_precio = [
##                            '.price',
##                            '.product-price',
##                            '[data-testid*="price"]',
##                            '.price-current',
##                            '.price-value',
##                            '[class*="price"]',
##                            '.valor',
##                            '.precio',
##                            '.money'
##                        ]
##                        
##                        precio = ''
##                        for selector_precio in selectores_precio:
##                            elem_precio = producto.select_one(selector_precio)
##                            if elem_precio:
##                                precio = elem_precio.get_text(strip=True)
##                                if precio and any(char.isdigit() for char in precio):
##                                    print(f"🛒 [JUMBO-SCRAPER] Precio encontrado: {precio}")
##                                    break
##                        
##                        # Buscar imagen
##                        img_elem = producto.select_one('img')
##                        imagen_url = ''
##                        if img_elem:
##                            imagen_url = img_elem.get('src', '') or img_elem.get('data-src', '') or img_elem.get('data-lazy', '')
##                            if imagen_url:
##                                if not imagen_url.startswith('http'):
##                                    imagen_url = f"https://www.jumbo.cl{imagen_url}"
##                                print(f"🛒 [JUMBO-SCRAPER] Imagen encontrada: {imagen_url}")
##                        
##                        # Buscar link del producto
##                        link_elem = producto.select_one('a')
##                        link_producto = url  # Por defecto la búsqueda
##                        if link_elem:
##                            href = link_elem.get('href', '')
##                            if href:
##                                if href.startswith('http'):
##                                    link_producto = href
##                                elif href.startswith('/'):
##                                    link_producto = f"https://www.jumbo.cl{href}"
##                                print(f"🛒 [JUMBO-SCRAPER] Link encontrado: {link_producto}")
##                        
##                        # Si encontramos información válida
##                        if nombre and len(nombre) > 3:
##                            resultado.update({
##                                'encontrado': True,
##                                'nombre': nombre,
##                                'precio': precio,
##                                'imagen_url': imagen_url,
##                                'link_producto': link_producto,
##                                'disponible': True
##                            })
##                            
##                            print(f"✅ [JUMBO-SCRAPER] ===== PRODUCTO ENCONTRADO EN JUMBO =====")
##                            print(f"📦 [JUMBO-SCRAPER] Nombre: {nombre}")
##                            print(f"💰 [JUMBO-SCRAPER] Precio: {precio}")
##                            print(f"🖼️ [JUMBO-SCRAPER] Imagen: {imagen_url}")
##                            print(f"🔗 [JUMBO-SCRAPER] Link: {link_producto}")
##                            
##                            return resultado
##                    
##                    print(f"❌ [JUMBO-SCRAPER] No se encontraron productos válidos en {url}")
##                else:
##                    print(f"❌ [JUMBO-SCRAPER] Error HTTP {response.status_code} en {url}")
##                    
##            except Exception as e:
##                print(f"❌ [JUMBO-SCRAPER] Error en {url}: {e}")
##                continue
##        
##        print(f"❌ [JUMBO-SCRAPER] No se encontró en ninguna URL de Jumbo")
##        
##    except Exception as e:
##        print(f"❌ [JUMBO-SCRAPER] Error general: {e}")
##    
##    return resultado
#
#
#
#
##from django.http import JsonResponse
##from django.shortcuts import render, redirect, get_object_or_404
##from django.contrib import messages
##from .models import Producto, ImagenPromocion
##from .forms import ProductoForm
##import re
##import csv
##from django.http import HttpResponse
##from django.contrib.admin.views.decorators import staff_member_required
### COMENTAR TEMPORALMENTE:
##import requests
##from bs4 import BeautifulSoup
##import json
##import time
##import threading
##from django.core.mail import send_mail
##from django.template.loader import render_to_string
##from django.conf import settings
##from datetime import datetime
##
##
##def limpiar_codigo_barras(codigo):
##    # Elimina espacios, tabulaciones, saltos de línea y retornos de carro
##    return re.sub(r'[\s\r\n\t]+', '', codigo)
##
##
##def buscar_producto(request):
##    codigo = request.GET.get('codigo_barras', '')
##    codigo_original = codigo
##    codigo = limpiar_codigo_barras(codigo)
##    print(f"Código recibido en backend (limpio): '{codigo}'")
##
##    # Obtener IP del cliente para el reporte
##    ip_cliente = request.META.get('HTTP_X_FORWARDED_FOR')
##    if ip_cliente:
##        ip_cliente = ip_cliente.split(',')[0]
##    else:
##        ip_cliente = request.META.get('REMOTE_ADDR', 'No disponible')
##
##    # Verificar si se solicita búsqueda exacta
##    busqueda_exacta = request.GET.get('busqueda_exacta') == 'true'
##    exacto = request.GET.get('exacto') == '1'
##    no_similar = request.GET.get('no_similar') == '1'
##
##    if not codigo:
##        return JsonResponse({'error': 'Código de barras no proporcionado'}, status=400)
##    if len(codigo) > 14:
##        return JsonResponse({'error': 'Código de barras demasiado largo'}, status=400)
##    
##    try:
##        # Paso 1: Intentar búsqueda exacta primero
##        producto = Producto.objects.filter(codigo_barras=codigo).first()
##        
##        # Si se solicita SOLO búsqueda exacta, no hacer búsquedas adicionales
##        if busqueda_exacta and exacto and no_similar:
##            # Solo intentar con/sin cero inicial para códigos que empiezan con 0
##            if not producto and codigo.startswith('0'):
##                sin_ceros = codigo.lstrip('0')
##                if sin_ceros:  # Asegurar que no quede vacío
##                    producto = Producto.objects.filter(codigo_barras=sin_ceros).first()
##                    if producto:
##                        print(f"Encontrado sin cero inicial: {producto.codigo_barras}")
##            
##            # También intentar agregando un cero si no se encontró
##            if not producto and not codigo.startswith('0'):
##                codigo_con_cero = '0' + codigo
##                producto = Producto.objects.filter(codigo_barras=codigo_con_cero).first()
##                if producto:
##                    print(f"Encontrado con cero inicial: {producto.codigo_barras}")
##        else:
##            # Lógica de búsqueda flexible original (solo si NO es búsqueda exacta)
##            if not producto:
##                # Intentar sin ceros iniciales (si comienza con 0)
##                if codigo.startswith('0'):
##                    sin_ceros = codigo.lstrip('0')
##                    if sin_ceros:  # Asegurar que no quede vacío
##                        producto = Producto.objects.filter(codigo_barras=sin_ceros).first()
##                else:
##                    # Intentar añadiendo ceros iniciales (hasta 13 o 14 dígitos)
##                    for i in range(1, 5):  # Probar añadiendo de 1 a 4 ceros
##                        codigo_con_ceros = '0' * i + codigo
##                        if len(codigo_con_ceros) in (13, 14):  # Si llegamos a 13 o 14 dígitos
##                            producto = Producto.objects.filter(codigo_barras=codigo_con_ceros).first()
##                            if producto:
##                                break
##            
##            # Paso 3: Si todavía no hay coincidencia, buscar en toda la base de datos por similitud
##            if not producto:
##                # Verificar en la base de datos por coincidencias con los mismos dígitos sin importar el orden
##                todos_productos = Producto.objects.all()
##                for p in todos_productos:
##                    # Si los mismos dígitos están presentes (sin importar orden)
##                    if len(p.codigo_barras) == len(codigo) and sorted(p.codigo_barras) == sorted(codigo):
##                        producto = p
##                        print(f"Coincidencia por dígitos similares: {p.codigo_barras}")
##                        break
##                    
##                    # Probar con código con o sin ceros iniciales
##                    codigo_db_sin_ceros = p.codigo_barras.lstrip('0')
##                    codigo_scan_sin_ceros = codigo.lstrip('0')
##                    
##                    if codigo_db_sin_ceros == codigo_scan_sin_ceros:
##                        producto = p
##                        print(f"Coincidencia sin ceros iniciales: {p.codigo_barras}")
##                        break
##                    
##                    # Verificar si los códigos contienen los mismos dígitos (posible inversión)
##                    # Por ejemplo, 417890039120 vs 041789003912
##                    if len(codigo_db_sin_ceros) == len(codigo_scan_sin_ceros) and set(codigo_db_sin_ceros) == set(codigo_scan_sin_ceros):
##                        # Si hay al menos 60% de coincidencia posicional
##                        coincidencias = sum(1 for a, b in zip(codigo_db_sin_ceros, codigo_scan_sin_ceros) if a == b)
##                        if coincidencias / len(codigo_db_sin_ceros) >= 0.6:
##                            producto = p
##                            print(f"Posible inversión/desorden detectada: {codigo} vs {p.codigo_barras}")
##                            break
##        
##        if producto:
##            print(f"✅ Producto encontrado: {producto.nombre} con código {producto.codigo_barras}")
##            return JsonResponse({
##                'nombre': producto.nombre,
##                'precio': str(producto.precio),
##                'sku': producto.sku or '',
##                'codigo_barras': producto.codigo_barras,
##                'codigo_original': codigo_original,
##                'precio_vecino': str(producto.precio_vecino) if producto.precio_vecino else None
##            })
##        
##        # Si llegamos aquí, no se encontró el producto
##        print(f"❌ PRODUCTO NO ENCONTRADO para código: {codigo}")
##        
##        # Enviar correo de notificación en un hilo separado
##        def enviar_correo_async():
##            try:
##                print(f"📧 [CORREO] Iniciando envío para código: {codigo}")
##                print(f"📧 [CORREO] IP cliente: {ip_cliente}")
##                print(f"📧 [CORREO] Email configurado: {getattr(settings, 'EMAIL_HOST_USER', 'NO CONFIGURADO')}")
##                print(f"📧 [CORREO] Admin email: {getattr(settings, 'ADMIN_EMAIL', 'NO CONFIGURADO')}")
##                
##                resultado = enviar_notificacion_producto_no_encontrado(codigo, ip_cliente)
##                
##                if resultado:
##                    print(f"✅ [CORREO] Envío exitoso")
##                else:
##                    print(f"❌ [CORREO] Error en envío")
##                    
##            except Exception as e:
##                print(f"💥 [CORREO] Excepción: {e}")
##                import traceback
##                print(f"💥 [CORREO] Traceback: {traceback.format_exc()}")
##        
##        # Ejecutar en segundo plano para no bloquear la respuesta
##        hilo_correo = threading.Thread(target=enviar_correo_async)
##        hilo_correo.daemon = True
##        hilo_correo.start()
##        print(f"🚀 Hilo de correo iniciado en segundo plano")
##        
##        return JsonResponse({
##            'error': 'Producto no encontrado',
##            'codigo_escaneado': codigo
##        }, status=404)
##        
##    except Exception as e:
##        print('💥 Error en buscar_producto:', str(e))
##        return JsonResponse({'error': 'Error interno: ' + str(e)}, status=500)
##
##
##def lector_precios(request):
##    productos = Producto.objects.all()
##    imagenes_promociones = ImagenPromocion.objects.all()
##    return render(request, 'elFaro/lector_precios.html', {
##        'productos': productos,
##        'imagenes_promociones': imagenes_promociones,
##    })
##
##
##def mantenedor_promociones(request):
##    if request.method == 'POST':
##        if 'eliminar_id' in request.POST:
##            ImagenPromocion.objects.filter(id=request.POST['eliminar_id']).delete()
##        elif 'imagen' in request.FILES:
##            ImagenPromocion.objects.create(
##                imagen=request.FILES['imagen'],
##                nombre=request.POST.get('nombre', '')
##            )
##        return redirect('mantenedor_promociones')
##    imagenes = ImagenPromocion.objects.all()
##    return render(request, 'elFaro/mantenedor_promociones.html', {'imagenes': imagenes})
##
##
##def agregar_producto(request):
##    if request.method == 'POST':
##        form = ProductoForm(request.POST)
##        if form.is_valid():
##            form.save()
##            messages.success(request, 'Producto agregado correctamente.')
##            return redirect('agregar_producto')
##    else:
##        form = ProductoForm()
##    return render(request, 'elFaro/agregar_producto.html', {'form': form})
##
##
##def lista_productos(request):
##    productos = Producto.objects.all()
##    return render(request, 'elFaro/lista_productos.html', {'productos': productos})
##
##
##def editar_producto(request, producto_id):
##    producto = get_object_or_404(Producto, id=producto_id)
##    if request.method == 'POST':
##        form = ProductoForm(request.POST, instance=producto)
##        if form.is_valid():
##            form.save()
##            return redirect('lista_productos')
##    else:
##        form = ProductoForm(instance=producto)
##    return render(request, 'elFaro/editar_producto.html', {'form': form, 'producto': producto})
##
##
##def eliminar_producto(request, producto_id):
##    producto = get_object_or_404(Producto, id=producto_id)
##    if request.method == 'POST':
##        producto.delete()
##        return redirect('lista_productos')
##    return redirect('lista_productos')
##
##
##@staff_member_required
##def export_productos_csv(request):
##    response = HttpResponse(content_type='text/csv')
##    response['Content-Disposition'] = 'attachment; filename="productos.csv"'
##    
##    # Crear el escritor CSV
##    writer = csv.writer(response)
##    
##    # Escribir encabezados
##    writer.writerow(['codigo_barras', 'nombre', 'precio', 'precio_vecino', 'sku'])
##    
##    # Escribir datos de productos
##    productos = Producto.objects.all()
##    for producto in productos:
##        # Convertir None a cadena vacía para evitar errores en CSV
##        precio_vecino = producto.precio_vecino if producto.precio_vecino else ''
##        sku = producto.sku if producto.sku else ''
##        
##        writer.writerow([
##            producto.codigo_barras,
##            producto.nombre,
##            producto.precio,
##            precio_vecino,
##            sku
##        ])
##    
##    return response
##
##
##def test_email(request):
##    """
##    Función temporal para probar el envío de correo
##    """
##    try:
##        print(f"📧 [TEST] Probando configuración de correo...")
##        print(f"📧 [TEST] EMAIL_HOST_USER: {getattr(settings, 'EMAIL_HOST_USER', 'NO CONFIGURADO')}")
##        print(f"📧 [TEST] ADMIN_EMAIL: {getattr(settings, 'ADMIN_EMAIL', 'NO CONFIGURADO')}")
##        
##        resultado = send_mail(
##            subject='🧪 Prueba de correo - El Faro',
##            message='Este es un correo de prueba para verificar la configuración.',
##            from_email=getattr(settings, 'NOTIFICATION_FROM_EMAIL', 'no-configurado@test.com'),
##            recipient_list=[getattr(settings, 'ADMIN_EMAIL', 'admin@test.com')],
##            fail_silently=False
##        )
##        
##        if resultado:
##            print(f"✅ [TEST] Correo de prueba enviado exitosamente")
##            return JsonResponse({'status': 'success', 'message': 'Correo enviado exitosamente'})
##        else:
##            print(f"❌ [TEST] Error enviando correo de prueba")
##            return JsonResponse({'status': 'error', 'message': 'Error enviando correo'})
##            
##    except Exception as e:
##        print(f"💥 [TEST] Error en prueba de correo: {e}")
##        return JsonResponse({'status': 'error', 'message': f'Error: {str(e)}'})
##
##
### Reemplazar COMPLETAMENTE la función buscar_producto_en_internet con esta versión:
##
##def buscar_producto_en_internet(codigo_barras):
##    """
##    Busca información del producto - CON SCRAPER DE JUMBO INCLUIDO
##    """
##    print(f"🔍 [INTERNET] ===== BÚSQUEDA CON SCRAPER JUMBO =====")
##    
##    resultados = {
##        'encontrado': False,
##        'nombre': '',
##        'descripcion': '',
##        'marca': '',
##        'categoria': '',
##        'fuente': '',
##        'imagen_url': '',
##        'precio_referencia': '',
##        'link_producto': ''
##    }
##    
##    # ===== PRIORIDAD 1: SCRAPER JUMBO.CL =====
##    try:
##        print(f"🛒 [1] SCRAPEANDO JUMBO.CL...")
##        resultado_jumbo = scrape_jumbo_cl(codigo_barras)
##        
##        if resultado_jumbo['encontrado']:
##            resultados.update({
##                'encontrado': True,
##                'nombre': resultado_jumbo['nombre'],
##                'imagen_url': resultado_jumbo['imagen_url'],
##                'precio_referencia': resultado_jumbo['precio'],
##                'link_producto': resultado_jumbo['link_producto'],
##                'fuente': 'Jumbo.cl (Scraping)'
##            })
##            
##            print(f"✅ [1] ===== ENCONTRADO EN JUMBO SCRAPING =====")
##            print(f"📦 [1] Nombre: {resultado_jumbo['nombre']}")
##            print(f"💰 [1] Precio: {resultado_jumbo['precio']}")
##            return resultados
##        
##        print(f"❌ [1] Scraper Jumbo: no encontró productos")
##        
##    except Exception as e:
##        print(f"❌ [1] Error en scraper Jumbo: {e}")
##    
##    # ===== FUENTE 2: Open Food Facts (RESPALDO) =====
##    try:
##        print(f"🌐 [2] OPEN FOOD FACTS - Código: {codigo_barras}")
##        
##        url = f"https://world.openfoodfacts.org/api/v0/product/{codigo_barras}.json"
##        response = requests.get(url, timeout=15)
##        
##        if response.status_code == 200:
##            data = response.json()
##            if data.get('status') == 1:
##                producto = data.get('product', {})
##                nombre = producto.get('product_name', '') or producto.get('product_name_es', '')
##                
##                if nombre and len(nombre) > 2:
##                    nombre_para_busqueda = nombre.replace(' ', '+')
##                    
##                    resultados.update({
##                        'encontrado': True,
##                        'nombre': nombre,
##                        'descripcion': producto.get('generic_name', ''),
##                        'marca': producto.get('brands', ''),
##                        'imagen_url': producto.get('image_url', ''),
##                        'link_producto': f"https://www.jumbo.cl/buscar?q={nombre_para_busqueda}",
##                        'precio_referencia': 'Consultar en tienda',
##                        'fuente': 'Open Food Facts + Link Jumbo'
##                    })
##                    
##                    print(f"✅ [2] ===== ENCONTRADO EN OPEN FOOD FACTS =====")
##                    return resultados
##    
##    except Exception as e:
##        print(f"❌ [2] Error en Open Food Facts: {e}")
##    
##    # ===== FUENTE 3: ENLACE MANUAL JUMBO =====
##    print(f"🔗 [3] CREANDO ENLACE MANUAL JUMBO")
##    
##    resultados.update({
##        'encontrado': True,
##        'nombre': f'Buscar código {codigo_barras} en Jumbo',
##        'link_producto': f"https://www.jumbo.cl/buscar?q={codigo_barras}",
##        'precio_referencia': 'Buscar manualmente',
##        'fuente': 'Enlace directo Jumbo'
##    })
##    
##    return resultados
##
##
##def enviar_notificacion_producto_no_encontrado(codigo_barras, ip_cliente=None):
##    """
##    Envía correo cuando no se encuentra un producto y busca sugerencias en internet
##    """
##    try:
##        print(f"📧 [EMAIL] Iniciando proceso de envío para código: {codigo_barras}")
##        
##        # Buscar información del producto en internet
##        print(f"🔍 [EMAIL] Buscando información en internet...")
##        info_producto = buscar_producto_en_internet(codigo_barras)
##        
##        # Datos para el correo
##        contexto = {
##            'codigo_barras': codigo_barras,
##            'fecha_hora': datetime.now().strftime('%d/%m/%Y %H:%M:%S'),
##            'ip_cliente': ip_cliente or 'No disponible',
##            'producto_sugerido': info_producto,
##            'encontrado_en_internet': info_producto['encontrado']
##        }
##        
##        # Log del resultado de la búsqueda
##        print(f"📧 [EMAIL] Contexto preparado. Encontrado en internet: {info_producto['encontrado']}")
##        if info_producto['encontrado']:
##            print(f"📧 [EMAIL] Producto encontrado: {info_producto['nombre']} - Fuente: {info_producto['fuente']}")
##        else:
##            print(f"📧 [EMAIL] No se encontró información en internet")
##        
##        # Renderizar el template del correo
##        mensaje_html = None
##        try:
##            mensaje_html = render_to_string('elFaro/email_producto_no_encontrado.html', contexto)
##            print(f"📧 [EMAIL] Template HTML renderizado correctamente")
##        except Exception as template_error:
##            print(f"⚠️ [EMAIL] Error renderizando template HTML: {template_error}")
##        
##        # Crear mensaje de texto dinámico
##        if info_producto['encontrado']:
##            seccion_internet = f"""✅ SUGERENCIA ENCONTRADA EN INTERNET:
##
##📦 Nombre: {info_producto['nombre']}
##{f"🏷️ Marca: {info_producto['marca']}" if info_producto['marca'] else ""}
##{f"📝 Descripción: {info_producto['descripcion']}" if info_producto['descripcion'] else ""}
##{f"🗂️ Categoría: {info_producto['categoria']}" if info_producto['categoria'] else ""}
##{f"💰 Precio referencia: {info_producto['precio_referencia']}" if info_producto['precio_referencia'] else ""}
##{f"🔗 Link del producto: {info_producto['link_producto']}" if info_producto['link_producto'] else ""}
##🔗 Fuente: {info_producto['fuente']}"""
##        else:
##            seccion_internet = "⚠️ NO SE ENCONTRÓ INFORMACIÓN EN INTERNET"
##
##        mensaje_texto = f"""PRODUCTO NO ENCONTRADO - El Faro Algarrobo
##
##Se ha buscado un producto que no existe en la base de datos:
##
##📊 Código de barras: {codigo_barras}
##🕐 Fecha y hora: {contexto['fecha_hora']}
##🌐 IP del cliente: {contexto['ip_cliente']}
##
##{seccion_internet}
##
##💡 ACCIONES RECOMENDADAS:
##• Verificar si el producto debe agregarse a la base de datos
##• Revisar si el código de barras es correcto
##• Considerar agregar el producto manualmente si es necesario
##{f"• Usar la información sugerida para crear el registro del producto" if info_producto['encontrado'] else ""}
##{f"• Visitar el link proporcionado para ver más detalles del producto" if info_producto['encontrado'] and info_producto['link_producto'] else ""}
##
##Este correo fue generado automáticamente por el sistema de lector de precios."""
##        
##        print(f"📧 [EMAIL] Mensaje de texto preparado")
##        
##        # Verificar configuración
##        from_email = getattr(settings, 'NOTIFICATION_FROM_EMAIL', None)
##        admin_email = getattr(settings, 'ADMIN_EMAIL', None)
##        
##        if not from_email or not admin_email:
##            print(f"❌ [EMAIL] Configuración incompleta - FROM: {from_email}, TO: {admin_email}")
##            return False
##        
##        print(f"📧 [EMAIL] Enviando desde: {from_email}")
##        print(f"📧 [EMAIL] Enviando hacia: {admin_email}")
##        
##        # Enviar correo
##        resultado = send_mail(
##            subject=f'🚫 Producto no encontrado - Código: {codigo_barras}',
##            message=mensaje_texto,
##            from_email=from_email,
##            recipient_list=[admin_email],
##            html_message=mensaje_html,
##            fail_silently=False
##        )
##        
##        if resultado:
##            print(f"✅ [EMAIL] Correo enviado exitosamente para código: {codigo_barras}")
##            if info_producto['encontrado']:
##                print(f"📦 [EMAIL] Sugerencia incluida: {info_producto['nombre']} ({info_producto['fuente']})")
##                if info_producto['link_producto']:
##                    print(f"🔗 [EMAIL] Link incluido: {info_producto['link_producto']}")
##            else:
##                print("❌ [EMAIL] No se encontró información en internet para incluir")
##        else:
##            print(f"❌ [EMAIL] Error enviando correo para código: {codigo_barras}")
##        
##        return resultado
##        
##    except Exception as e:
##        print(f"💥 [EMAIL] Error enviando correo para código {codigo_barras}: {e}")
##        import traceback
##        print(f"💥 [EMAIL] Traceback completo: {traceback.format_exc()}")
##        return False
##
##def test_busqueda_internet(request):
##    """
##    Función de prueba ESPECÍFICA para debug de búsqueda en internet
##    """
##    codigo = request.GET.get('codigo', '7802820005455')  # Código de Coca Cola por defecto
##    
##    print(f"🧪 [TEST] ===== INICIANDO PRUEBA BÚSQUEDA INTERNET =====")
##    print(f"🧪 [TEST] Código a buscar: {codigo}")
##    
##    # Verificar que requests funciona
##    try:
##        import requests
##        print(f"✅ [TEST] Requests importado correctamente")
##        
##        # Prueba básica de internet
##        test_response = requests.get('https://www.google.com', timeout=5)
##        print(f"✅ [TEST] Conexión a internet OK (Google status: {test_response.status_code})")
##        
##    except Exception as e:
##        print(f"❌ [TEST] Error con requests o internet: {e}")
##        return JsonResponse({'error': f'Error con requests: {e}'})
##    
##    # Probar función de búsqueda
##    try:
##        resultado = buscar_producto_en_internet(codigo)
##        print(f"🧪 [TEST] Resultado búsqueda: {resultado}")
##        
##        return JsonResponse({
##            'status': 'success',
##            'codigo_buscado': codigo,
##            'resultado': resultado,
##            'encontrado': resultado['encontrado']
##        })
##        
##    except Exception as e:
##        print(f"❌ [TEST] Error en búsqueda: {e}")
##        import traceback
##        print(f"❌ [TEST] Traceback: {traceback.format_exc()}")
##        return JsonResponse({'error': f'Error en búsqueda: {e}'})
##
##def test_correo_completo(request):
##    """
##    Test completo: buscar + enviar correo
##    """
##    codigo = request.GET.get('codigo', '8445291792388')
##    
##    print(f"📧 [TEST-CORREO] ===== PROBANDO CORREO COMPLETO =====")
##    
##    # Simular envío de correo
##    try:
##        resultado = enviar_notificacion_producto_no_encontrado(codigo, '127.0.0.1')
##        
##        return JsonResponse({
##            'status': 'success',
##            'codigo': codigo,
##            'correo_enviado': resultado,
##            'message': 'Revisa tu correo y la consola para ver los logs'
##        })
##        
##    except Exception as e:
##        print(f"❌ [TEST-CORREO] Error: {e}")
##        return JsonResponse({'error': str(e)})
##
##def scrape_jumbo_cl_selenium(codigo_barras):
##    """
##    Scraping de Jumbo.cl - VERSIÓN CON MANEJO DE REDIRECCIONES
##    """
##    print(f"🛒 [JUMBO-SELENIUM] ===== INICIANDO SCRAPING CON REDIRECCIONES =====")
##    print(f"🛒 [JUMBO-SELENIUM] Código: {codigo_barras}")
##    
##    resultado = {
##        'encontrado': False,
##        'nombre': '',
##        'precio': '',
##        'imagen_url': '',
##        'link_producto': '',
##        'descripcion': '',
##        'disponible': False
##    }
##    
##    try:
##        from selenium import webdriver
##        from selenium.webdriver.common.by import By
##        from selenium.webdriver.support.ui import WebDriverWait
##        from selenium.webdriver.support import expected_conditions as EC
##        from selenium.webdriver.chrome.options import Options
##        from selenium.common.exceptions import TimeoutException, NoSuchElementException
##        
##        # Configurar Chrome
##        chrome_options = Options()
##        chrome_options.add_argument("--headless")
##        chrome_options.add_argument("--no-sandbox")
##        chrome_options.add_argument("--disable-dev-shm-usage")
##        chrome_options.add_argument("--disable-gpu")
##        chrome_options.add_argument("--window-size=1920,1080")
##        chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
##        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
##        
##        print(f"🛒 [JUMBO-SELENIUM] Configurando navegador...")
##        
##        # Usar webdriver-manager
##        try:
##            from webdriver_manager.chrome import ChromeDriverManager
##            from selenium.webdriver.chrome.service import Service
##            
##            service = Service(ChromeDriverManager().install())
##            driver = webdriver.Chrome(service=service, options=chrome_options)
##            print(f"🛒 [JUMBO-SELENIUM] ChromeDriver automático OK")
##            
##        except ImportError:
##            # Fallback a ChromeDriver manual
##            import os
##            chromedriver_path = os.path.join(os.path.dirname(__file__), '..', 'chromedriver.exe')
##            
##            if os.path.exists(chromedriver_path):
##                service = Service(chromedriver_path)
##                driver = webdriver.Chrome(service=service, options=chrome_options)
##                print(f"🛒 [JUMBO-SELENIUM] ChromeDriver local OK")
##            else:
##                driver = webdriver.Chrome(options=chrome_options)
##                print(f"🛒 [JUMBO-SELENIUM] ChromeDriver del sistema OK")
##        
##        try:
##            url_inicial = f"https://www.jumbo.cl/buscar?q={codigo_barras}"
##            print(f"🛒 [JUMBO-SELENIUM] Navegando a: {url_inicial}")
##            
##            driver.get(url_inicial)
##            
##            # Esperar que la página cargue completamente
##            print(f"🛒 [JUMBO-SELENIUM] Esperando carga completa...")
##            WebDriverWait(driver, 25).until(
##                lambda driver: driver.execute_script("return document.readyState") == "complete"
##            )
##            
##            # CLAVE: Esperar más tiempo para que Jumbo procese la búsqueda y redirija
##            import time
##            time.sleep(12)  # Tiempo más largo para permitir redirecciones
##            
##            # Verificar si la URL cambió (redirección)
##            url_actual = driver.current_url
##            print(f"🛒 [JUMBO-SELENIUM] URL inicial: {url_inicial}")
##            print(f"🛒 [JUMBO-SELENIUM] URL actual: {url_actual}")
##            
##            if url_inicial != url_actual:
##                print(f"🛒 [JUMBO-SELENIUM] ✅ REDIRECCIÓN DETECTADA")
##                print(f"🛒 [JUMBO-SELENIUM] Nueva URL: {url_actual}")
##                
##                # Esperar un poco más después de la redirección
##                time.sleep(5)
##                
##                # Verificar si seguimos en una página de búsqueda
##                if '/buscar' in url_actual:
##                    print(f"🛒 [JUMBO-SELENIUM] ✅ Permanecemos en búsqueda después de redirección")
##                else:
##                    print(f"🛒 [JUMBO-SELENIUM] ⚠️ Redirección a página diferente")
##            else:
##                print(f"🛒 [JUMBO-SELENIUM] ❌ No hubo redirección - posible error")
##            
##            # Obtener HTML para análisis
##            html_content = driver.page_source
##            debug_file = f'debug_jumbo_selenium_{codigo_barras}.html'
##            with open(debug_file, 'w', encoding='utf-8') as f:
##                f.write(html_content)
##            print(f"🛒 [JUMBO-SELENIUM] HTML guardado: {debug_file}")
##            
##            # PASO 1: Verificar mensajes de error (pero ser más específicos)
##            mensajes_error_criticos = [
##                "No se encontraron productos para tu búsqueda",
##                "Sin resultados para tu búsqueda",
##                "No hay productos que coincidan"
##            ]
##
##            # NO incluir "404" genérico porque puede aparecer en otros contextos
##            error_encontrado = False
##            for mensaje in mensajes_error_criticos:
##                if mensaje.lower() in html_content.lower():
##                    print(f"🛒 [JUMBO-SELENIUM] ❌ Error crítico detectado: {mensaje}")
##                    error_encontrado = True
##                    break
##
##            # Verificar 404 de manera más específica
##            if "error 404" in html_content.lower() or "página no encontrada" in html_content.lower():
##                print(f"🛒 [JUMBO-SELENIUM] ❌ Error 404 confirmado")
##                error_encontrado = True
##
##            # NO salir inmediatamente - buscar productos de todas formas
##            if "Problemas con tu pedido" in html_content:
##                print(f"🛒 [JUMBO-SELENIUM] ⚠️ 'Problemas con tu pedido' detectado - podría ser temporal")
##
##            # Solo salir si hay error crítico confirmado
##            if error_encontrado:
##                print(f"🛒 [JUMBO-SELENIUM] ❌ Error crítico confirmado - saliendo")
##                return resultado
##
##            # CONTINUAR BUSCANDO PRODUCTOS incluso con mensajes de advertencia
##            print(f"🛒 [JUMBO-SELENIUM] ✅ Continuando búsqueda de productos...")
##            
##            # PASO 2: Buscar productos con selectores más específicos y robustos
##            selectores_productos = [
##                # Selectores VTEX más generales
##                '.vtex-search-result-3-x-galleryItem',
##                '.vtex-product-summary-2-x-container', 
##                '[data-testid*="product"]',
##                '.vtex-product-summary-2-x-element',
##                '.vtex-search-result-3-x-gallery > div',
##                '.vtex-search-result-3-x-gallery article',
##                
##                # Selectores de respaldo más amplios
##                'article[data-testid]',
##                'div[data-testid]',
##                '.shelf-item',
##                '.product-item',
##                '[class*="ProductCard"]',
##                '[class*="product-summary"]',
##                '[class*="product-card"]',
##                '[class*="ProductSummary"]',
##                
##                # Selectores genéricos amplios
##                'div[class*="product"]',
##                'article',
##                'div[class*="gallery"] > div',
##                'div[class*="shelf"] > div',
##                'div[class*="result"] > div'
##            ]
##            
##            productos_encontrados = []
##            selector_usado = ""
##            
##            for selector in selectores_productos:
##                try:
##                    elementos = driver.find_elements(By.CSS_SELECTOR, selector)
##                    print(f"🛒 [JUMBO-SELENIUM] Selector '{selector}': {len(elementos)} elementos")
##                    
##                    if elementos:
##                        # Filtrar elementos que NO sean mensajes de error
##                        productos_validos = []
##                        for elem in elementos:
##                            try:
##                                texto_elem = elem.text.lower()
##                                
##                                # Criterios más estrictos para validar productos
##                                es_error = any(error in texto_elem for error in [
##                                    'problemas con tu pedido', 
##                                    'error', 
##                                    'no encontrado',
##                                    'sin resultados'
##                                ])
##                                
##                                # Debe tener cierto contenido para ser considerado producto
##                                tiene_contenido = len(texto_elem) > 10
##                                
##                                # Buscar indicadores de producto (precio, nombre, etc.)
##                                indicadores_producto = any(indicador in texto_elem for indicador in [
##                                    '$', 'precio', 'agregar', 'comprar', 'ml', 'gr', 'kg', 'lt'
##                                ])
##                                
##                                if not es_error and tiene_contenido and (indicadores_producto or len(texto_elem) > 30):
##                                    productos_validos.append(elem)
##                                    print(f"🛒 [JUMBO-SELENIUM] ✅ Producto válido encontrado: {texto_elem[:50]}...")
##                                
##                            except Exception as filter_error:
##                                print(f"🛒 [JUMBO-SELENIUM] Error filtrando elemento: {filter_error}")
##                                continue
##                        
##                        if productos_validos:
##                            productos_encontrados = productos_validos[:5]  # Tomar primeros 5
##                            selector_usado = selector
##                            print(f"🛒 [JUMBO-SELENIUM] ✅ {len(productos_validos)} productos válidos con: {selector}")
##                            break
##                        else:
##                            print(f"🛒 [JUMBO-SELENIUM] ⚠️ Elementos encontrados pero filtrados como no válidos: {selector}")
##                            
##                except Exception as e:
##                    print(f"🛒 [JUMBO-SELENIUM] Error con selector {selector}: {e}")
##                    continue
##            
##            if not productos_encontrados:
##                print(f"🛒 [JUMBO-SELENIUM] ❌ No se encontraron productos válidos")
##                
##                # Debug mejorado: Buscar CUALQUIER texto que pueda ser útil
##                print(f"🛒 [JUMBO-SELENIUM] 🔍 DEBUG: Analizando TODO el contenido...")
##                
##                # Buscar cualquier texto que contenga el código de barras
##                if codigo_barras in html_content:
##                    print(f"🛒 [JUMBO-SELENIUM] ✅ Código {codigo_barras} encontrado en HTML")
##                else:
##                    print(f"🛒 [JUMBO-SELENIUM] ❌ Código {codigo_barras} NO encontrado en HTML")
##                
##                # Buscar elementos con texto relevante
##                try:
##                    todos_textos = driver.find_elements(By.XPATH, "//*[text()]")
##                    textos_relevantes = []
##                    
##                    for elem in todos_textos[:30]:  # Solo primeros 30
##                        try:
##                            texto = elem.text.strip()
##                            if texto and len(texto) > 10 and len(texto) < 200:
##                                # Filtrar textos que parezcan nombres de productos
##                                if any(palabra in texto.lower() for palabra in ['coca', 'leche', 'pan', 'agua', 'bebida', '$']):
##                                    textos_relevantes.append(texto[:100])
##                        except:
##                            continue
##                    
##                    if textos_relevantes:
##                        print(f"🛒 [JUMBO-SELENIUM] 📝 Textos relevantes encontrados:")
##                        for i, texto in enumerate(textos_relevantes[:5]):
##                            print(f"🛒 [JUMBO-SELENIUM]   {i+1}. {texto}")
##                    else:
##                        print(f"🛒 [JUMBO-SELENIUM] ❌ No se encontraron textos relevantes")
##                        
##                except Exception as debug_error:
##                    print(f"🛒 [JUMBO-SELENIUM] Error en debug: {debug_error}")
##                
##                return resultado
##            
##            # PASO 3: Analizar productos encontrados
##            print(f"🛒 [JUMBO-SELENIUM] 📦 Analizando {len(productos_encontrados)} productos...")
##            
##            for i, producto in enumerate(productos_encontrados):
##                try:
##                    print(f"🛒 [JUMBO-SELENIUM] --- Producto {i+1} ---")
##                    
##                    # Obtener todo el texto del producto para debug
##                    texto_completo = producto.text.strip()
##                    print(f"🛒 [JUMBO-SELENIUM] Texto completo: {texto_completo[:150]}...")
##                    
##                    # Verificar que NO sea un mensaje de error
##                    if any(error in texto_completo.lower() for error in ['problemas con tu pedido', 'error', 'no encontrado']):
##                        print(f"🛒 [JUMBO-SELENIUM] ⚠️ Saltando elemento que parece ser error")
##                        continue
##                    
##                    # Buscar nombre del producto
##                    nombre = ""
##                    selectores_nombre = [
##                        'a[title]',  # Títulos de enlaces (muy común en productos)
##                        'h1, h2, h3, h4',
##                        '[class*="productName"]',
##                        '[class*="product-name"]',
##                        '[class*="name"]',
##                        '[class*="title"]',
##                        '.vtex-product-summary-2-x-productNameContainer',
##                        '.vtex-store-components-3-x-productBrand',
##                        'span[class*="brand"]'
##                    ]
##                    
##                    for selector_nombre in selectores_nombre:
##                        try:
##                            elementos_nombre = producto.find_elements(By.CSS_SELECTOR, selector_nombre)
##                            for elem in elementos_nombre:
##                                texto = elem.text.strip() if elem.text else elem.get_attribute('title')
##                                if texto and len(texto) > 5 and codigo_barras not in texto:
##                                    # Verificar que parezca un nombre de producto real
##                                    if not any(error in texto.lower() for error in ['problemas', 'error', 'buscar']):
##                                        nombre = texto
##                                        print(f"🛒 [JUMBO-SELENIUM] ✅ Nombre encontrado: {nombre}")
##                                        break
##                            if nombre:
##                                break
##                        except:
##                            continue
##                    
##                    # Si no se encontró nombre específico, usar parte del texto completo
##                    if not nombre and texto_completo and len(texto_completo) > 10:
##                        # Tomar la línea más larga que no contenga caracteres especiales
##                        lineas = texto_completo.split('\n')
##                        mejor_linea = ""
##                        for linea in lineas:
##                            linea = linea.strip()
##                            if (linea and 
##                                len(linea) > len(mejor_linea) and 
##                                len(linea) < 100 and
##                                not any(char in linea for char in ['$', '€', '₹']) and
##                                not any(error in linea.lower() for error in ['problemas', 'error', 'buscar'])):
##                                mejor_linea = linea
##                        
##                        if mejor_linea:
##                            nombre = mejor_linea
##                            print(f"🛒 [JUMBO-SELENIUM] ✅ Nombre (del texto): {nombre}")
##                    
##                    if not nombre:
##                        print(f"🛒 [JUMBO-SELENIUM] ❌ No se encontró nombre válido para producto {i+1}")
##                        continue
##                    
##                    # Buscar precio
##                    precio = ""
##                    selectores_precio = [
##                        '[class*="sellingPrice"]',
##                        '[class*="price-value"]',
##                        '[class*="price"]',
##                        '[class*="Price"]',
##                        '[class*="currency"]',
##                        '[data-testid*="price"]',
##                        '.vtex-product-price-1-x-sellingPriceValue',
##                        'span[class*="price"]'
##                    ]
##                    
##                    for selector_precio in selectores_precio:
##                        try:
##                            elem_precio = producto.find_element(By.CSS_SELECTOR, selector_precio)
##                            if elem_precio:
##                                precio_texto = elem_precio.text.strip()
##                                if precio_texto and any(char.isdigit() for char in precio_texto) and '$' in precio_texto:
##                                    precio = precio_texto
##                                    print(f"🛒 [JUMBO-SELENIUM] ✅ Precio encontrado: {precio}")
##                                    break
##                        except:
##                            continue
##                    
##                    # Si no se encontró precio específico, buscar en el texto completo
##                    if not precio:
##                        import re
##                        patron_precio = r'\$[\d,.]+(?:\.\d{2})?'
##                        matches = re.findall(patron_precio, texto_completo)
##                        if matches:
##                            precio = matches[0]
##                            print(f"🛒 [JUMBO-SELENIUM] ✅ Precio (regex): {precio}")
##                    
##                    # Buscar imagen
##                    imagen_url = ""
##                    try:
##                        img_elem = producto.find_element(By.CSS_SELECTOR, 'img')
##                        if img_elem:
##                            src = img_elem.get_attribute('src') or img_elem.get_attribute('data-src')
##                            if src and 'svg' not in src.lower() and 'placeholder' not in src.lower():
##                                imagen_url = src if src.startswith('http') else f"https://www.jumbo.cl{src}"
##                                print(f"🛒 [JUMBO-SELENIUM] ✅ Imagen: {imagen_url}")
##                    except:
##                        pass
##                    
##                    # Buscar link del producto
##                    link_producto = url_actual if url_actual else url_inicial
##                    try:
##                        link_elem = producto.find_element(By.CSS_SELECTOR, 'a')
##                        if link_elem:
##                            href = link_elem.get_attribute('href')
##                            if href and ('/p/' in href or '/producto/' in href):
##                                link_producto = href if href.startswith('http') else f"https://www.jumbo.cl{href}"
##                                print(f"🛒 [JUMBO-SELENIUM] ✅ Link: {link_producto}")
##                    except:
##                        pass
##                    
##                    # Si encontramos información válida
##                    if nombre and len(nombre) > 5:
##                        resultado.update({
##                            'encontrado': True,
##                            'nombre': nombre,
##                            'precio': precio,
##                            'imagen_url': imagen_url,
##                            'link_producto': link_producto,
##                            'disponible': True
##                        })
##                        
##                        print(f"🛒 [JUMBO-SELENIUM] 🎉 ===== PRODUCTO ENCONTRADO =====")
##                        print(f"🛒 [JUMBO-SELENIUM] 📦 Nombre: {nombre}")
##                        print(f"🛒 [JUMBO-SELENIUM] 💰 Precio: {precio}")
##                        print(f"🛒 [JUMBO-SELENIUM] 🖼️ Imagen: {imagen_url}")
##                        print(f"🛒 [JUMBO-SELENIUM] 🔗 Link: {link_producto}")
##                        
##                        break
##                        
##                except Exception as e:
##                    print(f"🛒 [JUMBO-SELENIUM] ❌ Error analizando producto {i+1}: {e}")
##                    continue
##            
##            if not resultado['encontrado']:
##                print(f"🛒 [JUMBO-SELENIUM] ❌ No se pudieron extraer datos válidos")
##                
##        except Exception as e:
##            print(f"🛒 [JUMBO-SELENIUM] ❌ Error durante navegación: {e}")
##            import traceback
##            print(f"🛒 [JUMBO-SELENIUM] Traceback: {traceback.format_exc()}")
##            
##        finally:
##            driver.quit()
##            print(f"🛒 [JUMBO-SELENIUM] 🔒 Navegador cerrado")
##            
##    except ImportError as e:
##        print(f"🛒 [JUMBO-SELENIUM] ❌ Error de importación: {e}")
##        print(f"🛒 [JUMBO-SELENIUM] 💡 Ejecuta: pip install selenium webdriver-manager")
##        
##    except Exception as e:
##        print(f"🛒 [JUMBO-SELENIUM] ❌ Error general: {e}")
##    
##    return resultado
##
##
#def test_scraper_selenium(request):
#   """
#   Test del scraper con Selenium
#   """
#   codigo = request.GET.get('codigo', '7802820005455')
#   
#   print(f"🧪 [TEST-SELENIUM] ===== PROBANDO SCRAPER SELENIUM =====")
#   
#   try:
#       resultado = scrape_jumbo_cl_selenium(codigo)
#       
#       return JsonResponse({
#           'status': 'success',
#           'codigo': codigo,
#           'scraper_result': resultado,
#           'html_guardado': f'debug_jumbo_selenium_{codigo}.html',
#           'metodo': 'Selenium con JavaScript'
#       })
#       
#   except Exception as e:
#       return JsonResponse({'error': str(e)})
#
#
#def debug_jumbo_html(request):
#   """
#   Función para analizar en detalle el HTML de Jumbo
#   """
#   codigo = request.GET.get('codigo', '7802820005455')
#   
#   try:
#       headers = {
#           'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
#       }
#       
#       url = f"https://www.jumbo.cl/buscar?q={codigo}"
#       response = requests.get(url, headers=headers, timeout=20)
#       
#       if response.status_code == 200:
#           soup = BeautifulSoup(response.content, 'html.parser')
#           
#           # Buscar TODOS los elementos que contengan texto
#           elementos_con_texto = []
#           for elem in soup.find_all(text=True):
#               texto = elem.strip()
#               if texto and len(texto) > 5 and not texto.startswith('<'):
#                   elementos_con_texto.append({
#                       'texto': texto,
#                       'parent_tag': elem.parent.name if elem.parent else 'unknown',
#                       'parent_class': elem.parent.get('class', []) if elem.parent else []
#                   })
#           
#           return JsonResponse({
#               'status': 'success',
#               'url': url,
#               'status_code': response.status_code,
#               'elementos_encontrados': len(elementos_con_texto),
#               'primeros_20_elementos': elementos_con_texto[:20]
#           })
#       else:
#           return JsonResponse({'error': f'HTTP {response.status_code}'})
#           
#   except Exception as e:
#       return JsonResponse({'error': str(e)})
#
#def scrape_jumbo_cl(codigo_barras):
#   """
#   Versión simple de scraping de Jumbo.cl (sin Selenium)
#   """
#   print(f"🛒 [JUMBO-SIMPLE] ===== SCRAPING SIMPLE JUMBO =====")
#   print(f"🛒 [JUMBO-SIMPLE] Código: {codigo_barras}")
#   
#   resultado = {
#       'encontrado': False,
#       'nombre': '',
#       'precio': '',
#       'imagen_url': '',
#       'link_producto': '',
#       'descripcion': '',
#       'disponible': False
#   }
#   
#   try:
#       headers = {
#           'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
#           'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
#           'Accept-Language': 'es-CL,es;q=0.9,en;q=0.8',
#           'Accept-Encoding': 'gzip, deflate, br',
#           'Connection': 'keep-alive',
#           'Upgrade-Insecure-Requests': '1'
#       }
#       
#       url = f"https://www.jumbo.cl/buscar?q={codigo_barras}"
#       print(f"🛒 [JUMBO-SIMPLE] URL: {url}")
#       
#       response = requests.get(url, headers=headers, timeout=15)
#       print(f"🛒 [JUMBO-SIMPLE] Status Code: {response.status_code}")
#       
#       if response.status_code == 200:
#           # Guardar HTML para debug
#           with open(f'debug_jumbo_simple_{codigo_barras}.html', 'w', encoding='utf-8') as f:
#               f.write(response.text)
#           print(f"🛒 [JUMBO-SIMPLE] HTML guardado para debug")
#           
#           # Como Jumbo es SPA, probablemente no encontraremos productos aquí
#           # pero intentemos buscar alguna información básica
#           soup = BeautifulSoup(response.content, 'html.parser')
#           
#           # Buscar si hay algún mensaje de "no encontrado"
#           if "No se encontraron productos" in response.text:
#               print(f"🛒 [JUMBO-SIMPLE] Jumbo reporta: No se encontraron productos")
#           else:
#               # Ver si hay algún elemento que sugiera que se encontró algo
#               scripts = soup.find_all('script')
#               for script in scripts:
#                   if script.string and codigo_barras in str(script.string):
#                       print(f"🛒 [JUMBO-SIMPLE] Código encontrado en JavaScript")
#                       break
#               
#               print(f"🛒 [JUMBO-SIMPLE] Scraping simple no encuentra productos (SPA)")
#       
#       return resultado
#       
#   except Exception as e:
#       print(f"❌ [JUMBO-SIMPLE] Error: {e}")
#       return resultado
#
##def analizar_html_capturado(request):
##    """
##    Analiza el HTML capturado por Selenium para ver qué contiene
##    """
##    codigo = request.GET.get('codigo', '7702133815782')
##    archivo_html = f'debug_jumbo_selenium_{codigo}.html'
##    
##    try:
##        import os
##        if not os.path.exists(archivo_html):
##            return JsonResponse({
##                'error': f'Archivo {archivo_html} no encontrado',
##                'sugerencia': 'Ejecuta primero test-selenium para generar el archivo'
##            })
##        
##        with open(archivo_html, 'r', encoding='utf-8') as f:
##            content = f.read()
##        
##        print(f"🔍 [ANALISIS] Analizando {archivo_html}")
##        print(f"🔍 [ANALISIS] Tamaño del archivo: {len(content)} caracteres")
##        
##        # Buscar elementos clave
##        analisis = {
##            'tamaño_archivo': len(content),
##            'tiene_productos': False,
##            'tiene_errores': False,
##            'tiene_javascript': False,
##            'selectores_encontrados': [],
##            'textos_relevantes': [],
##            'mensajes_importantes': []
##        }
##        
##        # Detectar si hay productos VTEX
##        selectores_vtex = [
##            'vtex-search-result',
##            'vtex-product-summary',
##            'product-summary',
##            'galleryItem',
##            'ProductCard'
##        ]
##        
##        for selector in selectores_vtex:
##            if selector in content:
##                analisis['selectores_encontrados'].append(selector)
##        
##        # Buscar mensajes específicos
##        mensajes = [
##            'No se encontraron productos',
##            'Problemas con tu pedido',
##            'Sin resultados',
##            'You need to enable JavaScript',
##            'product-summary',
##            'shelf-item',
##            'price'
##        ]
##        
##        for mensaje in mensajes:
##            if mensaje.lower() in content.lower():
##                analisis['mensajes_importantes'].append(mensaje)
##                if 'producto' in mensaje.lower() or 'encontr' in mensaje.lower():
##                    analisis['tiene_productos'] = True
##                if 'problema' in mensaje.lower() or 'error' in mensaje.lower():
##                    analisis['tiene_errores'] = True
##                if 'javascript' in mensaje.lower():
##                    analisis['tiene_javascript'] = True
##        
##        # Extraer fragmentos de HTML importantes
##        soup = BeautifulSoup(content, 'html.parser')
##        
##        # Buscar divs con clases de producto
##        divs_producto = soup.find_all('div', class_=lambda x: x and ('product' in str(x).lower() or 'item' in str(x).lower()))[:5]
##        for div in divs_producto:
##            analisis['textos_relevantes'].append({
##                'tipo': 'div_producto',
##                'class': div.get('class', []),
##                'texto': div.get_text(strip=True)[:100] if div.get_text(strip=True) else 'Sin texto'
##            })
##        
##        # Buscar scripts que puedan contener datos
##        scripts = soup.find_all('script')
##        for script in scripts[:3]:  # Solo primeros 3
##            if script.string and len(script.string) > 100:
##                analisis['textos_relevantes'].append({
##                    'tipo': 'script',
##                    'contenido': script.string[:200] + '...'
##                })
##        
##        return JsonResponse({
##            'status': 'success',
##            'archivo_analizado': archivo_html,
##            'codigo': codigo,
##            'analisis': analisis
##        })
##        
##    except Exception as e:
##        return JsonResponse({'error': f'Error analizando HTML: {e}'})
##
##def test_codigos_reales_jumbo(request):
##    """
##    Test con códigos que sabemos que existen en supermercados chilenos
##    """
##    # Códigos más comunes en Chile
##    codigos_test = [
##        '7702133815782',  # Formato genérico Soprole/Colun
##        '7891000000000',  # Formato Nestlé
##        '7613000000000',  # Formato Kraft/Mondelez
##        '7411000000000',  # Formato Coca-Cola
##        '7796000000000',  # Formato Arcor
##        # Intentemos con códigos más específicos
##        '7411001775003',  # Coca Cola 350ml (formato más probable)
##        '7802800710219',  # Leche Soprole
##        '7613034626844',  # Oreo Original
##        # También el formato del ejemplo original pero sin el último dígito
##        '741100188945'    # Sin el último 8
##    ]
##    
##    resultados = []
##    
##    for codigo in codigos_test:
##        print(f"🧪 [TEST-CODIGOS] Probando código: {codigo}")
##        
##        try:
##            resultado = scrape_jumbo_cl_selenium(codigo)
##            
##            resultados.append({
##                'codigo': codigo,
##                'encontrado': resultado['encontrado'],
##                'nombre': resultado['nombre'],
##                'precio': resultado['precio']
##            })
##            
##            # Si encontramos uno, parar para no sobrecargar
##            if resultado['encontrado']:
##                print(f"✅ [TEST-CODIGOS] ¡Producto encontrado! Parando test")
##                break
##                
##        except Exception as e:
##            print(f"❌ [TEST-CODIGOS] Error con código {codigo}: {e}")
##            resultados.append({
##                'codigo': codigo,
##                'error': str(e)
##            })
##    
##    return JsonResponse({
##        'status': 'success',
##        'resultados': resultados,
##        'total_probados': len(resultados)
##    })
##
##
##def buscar_producto_por_nombre_jumbo(nombre_producto):
##    """
##    Buscar en Jumbo por nombre en lugar de código de barras
##    """
##    print(f"🛒 [JUMBO-NOMBRE] Buscando por nombre: {nombre_producto}")
##    
##    resultado = {
##        'encontrado': False,
##        'nombre': '',
##        'precio': '',
##        'imagen_url': '',
##        'link_producto': '',
##        'disponible': False
##    }
##    
##    try:
##        from selenium import webdriver
##        from selenium.webdriver.common.by import By
##        from selenium.webdriver.support.ui import WebDriverWait
##        from selenium.webdriver.chrome.options import Options
##        
##        chrome_options = Options()
##        chrome_options.add_argument("--headless")
##        chrome_options.add_argument("--no-sandbox")
##        chrome_options.add_argument("--disable-dev-shm-usage")
##        
##        # Usar webdriver-manager
##        from webdriver_manager.chrome import ChromeDriverManager
##        from selenium.webdriver.chrome.service import Service
##        
##        service = Service(ChromeDriverManager().install())
##        driver = webdriver.Chrome(service=service, options=chrome_options)
##        
##        try:
##            # Buscar por nombre (más probable que funcione)
##            nombre_url = nombre_producto.replace(' ', '+')
##            url = f"https://www.jumbo.cl/buscar?q={nombre_url}"
##            print(f"🛒 [JUMBO-NOMBRE] URL: {url}")
##            
##            driver.get(url)
##            
##            # Esperar carga
##            WebDriverWait(driver, 20).until(
##                lambda driver: driver.execute_script("return document.readyState") == "complete"
##            )
##            
##            import time
##            time.sleep(8)
##            
##            # Buscar productos
##            selectores = [
##                '.vtex-search-result-3-x-galleryItem',
##                '.vtex-product-summary-2-x-container',
##                '[data-testid*="product"]'
##            ]
##            
##            for selector in selectores:
##                elementos = driver.find_elements(By.CSS_SELECTOR, selector)
##                if elementos:
##                    print(f"🛒 [JUMBO-NOMBRE] Encontrados {len(elementos)} productos")
##                    
##                    producto = elementos[0]  # Tomar el primero
##                    
##                    # Extraer información
##                    try:
##                        nombre_elem = producto.find_element(By.CSS_SELECTOR, 'h1, h2, h3, a[title]')
##                        nombre = nombre_elem.text or nombre_elem.get_attribute('title')
##                        
##                        try:
##                            precio_elem = producto.find_element(By.CSS_SELECTOR, '[class*="price"]')
##                            precio = precio_elem.text
##                        except:
##                            precio = "Consultar precio"
##                        
##                        try:
##                            img_elem = producto.find_element(By.CSS_SELECTOR, 'img')
##                            imagen_url = img_elem.get_attribute('src')
##                        except:
##                            imagen_url = ""
##                        
##                        resultado.update({
##                            'encontrado': True,
##                            'nombre': nombre,
##                            'precio': precio,
##                            'imagen_url': imagen_url,
##                            'link_producto': url
##                        })
##                        
##                        print(f"🛒 [JUMBO-NOMBRE] ✅ Encontrado: {nombre}")
##                        break
##                        
##                    except Exception as e:
##                        print(f"🛒 [JUMBO-NOMBRE] Error extrayendo info: {e}")
##                        continue
##        
##        finally:
##            driver.quit()
##    
##    except Exception as e:
##        print(f"🛒 [JUMBO-NOMBRE] Error: {e}")
##    
##    return resultado
##
##def test_productos_populares_jumbo(request):
##    """
##    Test con productos que sabemos que existen en Chile
##    """
##    productos_populares = [
##        'coca cola',
##        'leche soprole',
##        'pan bimbo', 
##        'aceite chef',
##        'arroz grado 1',
##        'azucar iansa',
##        'margarina doriana',
##        'fideos carozzi',
##        'pollo entero',
##        'huevos rojos'
##    ]
##    
##    resultados = []
##    
##    for producto in productos_populares:
##        print(f"🧪 [TEST-POPULAR] Probando producto: {producto}")
##        
##        try:
##            resultado = scrape_jumbo_cl_selenium(producto)
##            
##            resultados.append({
##                'producto': producto,
##                'encontrado': resultado['encontrado'],
##                'nombre': resultado['nombre'],
##                'precio': resultado['precio']
##            })
##            
##            # Si encontramos uno, continuar para obtener más ejemplos
##            if resultado['encontrado']:
##                print(f"✅ [TEST-POPULAR] ¡Producto encontrado: {producto}!")
##                # No hacer break para seguir probando
##                
##        except Exception as e:
##            print(f"❌ [TEST-POPULAR] Error con producto {producto}: {e}")
##            resultados.append({
##                'producto': producto,
##                'error': str(e)
##            })
##    
##    return JsonResponse({
##        'status': 'success',
##        'resultados': resultados,
##        'productos_encontrados': [r for r in resultados if r.get('encontrado', False)],
##        'total_probados': len(resultados)
##    })
##
##
##def test_url_directa_jumbo(request):
##    """
##    Test navegando directamente a URLs de productos conocidos
##    """
##    urls_productos = [
##        'https://www.jumbo.cl/coca-cola-desechable-350-cc/p',
##        'https://www.jumbo.cl/leche-entera-soprole-1-litro/p',
##        'https://www.jumbo.cl/aceite-chef-900-cc/p',
##        'https://www.jumbo.cl/arroz-grado-1-tio-pelao-1-kg/p'
##    ]
##    
##    resultados = []
##    
##    try:
##        from selenium import webdriver
##        from selenium.webdriver.common.by import By
##        from selenium.webdriver.support.ui import WebDriverWait
##        from selenium.webdriver.chrome.options import Options
##        from webdriver_manager.chrome import ChromeDriverManager
##        from selenium.webdriver.chrome.service import Service
##        
##        chrome_options = Options()
##        chrome_options.add_argument("--headless")
##        chrome_options.add_argument("--no-sandbox")
##        chrome_options.add_argument("--disable-dev-shm-usage")
##        
##        service = Service(ChromeDriverManager().install())
##        driver = webdriver.Chrome(service=service, options=chrome_options)
##        
##        for url in urls_productos:
##            try:
##                print(f"🧪 [TEST-URL] Probando URL: {url}")
##                
##                driver.get(url)
##                
##                # Esperar carga
##                WebDriverWait(driver, 15).until(
##                    lambda driver: driver.execute_script("return document.readyState") == "complete"
##                )
##                
##                import time
##                time.sleep(5)
##                
##                # Buscar elementos de producto
##                nombre = ""
##                precio = ""
##                
##                try:
##                    # Buscar nombre del producto
##                    nombre_elem = driver.find_element(By.CSS_SELECTOR, 'h1, .vtex-store-components-3-x-productNameContainer, [class*="productName"]')
##                    nombre = nombre_elem.text.strip()
##                except:
##                    pass
##                
##                try:
##                    # Buscar precio
##                    precio_elem = driver.find_element(By.CSS_SELECTOR, '[class*="sellingPrice"], [class*="price"]')
##                    precio = precio_elem.text.strip()
##                except:
##                    pass
##                
##                resultado = {
##                    'url': url,
##                    'encontrado': bool(nombre),
##                    'nombre': nombre,
##                    'precio': precio,
##                    'status': 'producto encontrado' if nombre else 'página cargada sin producto'
##                }
##                
##                resultados.append(resultado)
##                print(f"✅ [TEST-URL] Resultado: {resultado}")
##                
##                # Si encontramos uno válido, parar
##                if nombre:
##                    print(f"🎉 [TEST-URL] ¡Producto válido encontrado!")
##                    break
##                    
##            except Exception as e:
##                print(f"❌ [TEST-URL] Error con URL {url}: {e}")
##                resultados.append({
##                    'url': url,
##                    'error': str(e)
##                })
##        
##        driver.quit()
##        
##    except Exception as e:
##        print(f"❌ [TEST-URL] Error general: {e}")
##        return JsonResponse({'error': str(e)})
##    
##    return JsonResponse({
##        'status': 'success',
##        'resultados': resultados,
##        'productos_validos': [r for r in resultados if r.get('encontrado', False)]
##    })