#!/usr/bin/env python3
import sqlite3
import decimal
import re

def deep_clean_database():
    """Limpieza profunda de la base de datos para eliminar TODOS los datos corruptos"""
    try:
        conn = sqlite3.connect('db.sqlite3')
        cursor = conn.cursor()
        
        print("Iniciando limpieza profunda de la base de datos...")
        
        # Obtener TODOS los registros para inspección manual
        cursor.execute('SELECT id, codigo_barras, precio, precio_vecino FROM elFaro_producto')
        all_products = cursor.fetchall()
        
        print(f"Total de productos a inspeccionar: {len(all_products)}")
        
        invalid_ids = []
        
        for product in all_products:
            product_id, codigo, precio, precio_vecino = product
            is_invalid = False
            
            # Convertir a string para análisis
            precio_str = str(precio) if precio is not None else "None"
            precio_vecino_str = str(precio_vecino) if precio_vecino is not None else "None"
            
            # Verificar múltiples condiciones problemáticas
            try:
                # Verificar si contiene decimales
                if '.' in precio_str or '.' in precio_vecino_str:
                    is_invalid = True
                    print(f"Producto {product_id} tiene decimales: precio={precio_str}, precio_vecino={precio_vecino_str}")
                
                # Verificar si contiene caracteres no numéricos (excepto None/0)
                if precio_str not in ['None', '0'] and not precio_str.isdigit():
                    is_invalid = True
                    print(f"Producto {product_id} precio no numérico: {precio_str}")
                
                if precio_vecino_str not in ['None', '0'] and not precio_vecino_str.isdigit():
                    is_invalid = True
                    print(f"Producto {product_id} precio_vecino no numérico: {precio_vecino_str}")
                
                # Verificar si Django puede convertir los valores
                if precio is not None and precio != '':
                    try:
                        decimal.Decimal(str(precio)).quantize(decimal.Decimal('1'))
                    except (decimal.InvalidOperation, ValueError):
                        is_invalid = True
                        print(f"Producto {product_id} precio inválido para Django: {precio_str}")
                
                if precio_vecino is not None and precio_vecino != '':
                    try:
                        decimal.Decimal(str(precio_vecino)).quantize(decimal.Decimal('1'))
                    except (decimal.InvalidOperation, ValueError):
                        is_invalid = True
                        print(f"Producto {product_id} precio_vecino inválido para Django: {precio_vecino_str}")
                
                # Verificar valores extremadamente largos o con formato raro
                if len(precio_str) > 10 or len(precio_vecino_str) > 10:
                    is_invalid = True
                    print(f"Producto {product_id} valores muy largos: precio={precio_str}, precio_vecino={precio_vecino_str}")
                
            except Exception as e:
                is_invalid = True
                print(f"Producto {product_id} error en validación: {e}")
            
            if is_invalid:
                invalid_ids.append(product_id)
        
        print(f"\nEncontrados {len(invalid_ids)} productos con datos inválidos")
        
        if invalid_ids:
            # Mostrar algunos ejemplos antes de eliminar
            print("\nEjemplos de productos que serán eliminados:")
            for i, pid in enumerate(invalid_ids[:10]):
                cursor.execute('SELECT id, codigo_barras, precio, precio_vecino FROM elFaro_producto WHERE id = ?', (pid,))
                product = cursor.fetchone()
                if product:
                    print(f"  {product}")
            
            if len(invalid_ids) > 10:
                print(f"  ... y {len(invalid_ids) - 10} más")
            
            # Confirmar eliminación
            response = input(f"\n¿Eliminar estos {len(invalid_ids)} productos? (s/N): ")
            if response.lower() in ['s', 'si', 'y', 'yes']:
                # Eliminar productos inválidos
                placeholders = ','.join(['?' for _ in invalid_ids])
                cursor.execute(f'DELETE FROM elFaro_producto WHERE id IN ({placeholders})', invalid_ids)
                conn.commit()
                print(f"Eliminados {len(invalid_ids)} productos con datos inválidos")
            else:
                print("Eliminación cancelada")
        else:
            print("No se encontraron productos con datos inválidos")
        
        # Verificación final
        cursor.execute('SELECT COUNT(*) FROM elFaro_producto')
        final_count = cursor.fetchone()[0]
        print(f"\nProductos restantes: {final_count}")
        
        conn.close()
        print("Limpieza completada")
        
    except Exception as e:
        print(f"Error durante la limpieza: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    deep_clean_database()
