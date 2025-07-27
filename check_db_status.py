#!/usr/bin/env python3
import sqlite3
import decimal

def check_database_status():
    """Verifica el estado actual de la base de datos"""
    try:
        conn = sqlite3.connect('db.sqlite3')
        cursor = conn.cursor()
        
        # Contar productos
        cursor.execute('SELECT COUNT(*) FROM elFaro_producto')
        total_productos = cursor.fetchone()[0]
        print(f"Total productos: {total_productos}")
        
        # Verificar estructura de la tabla
        cursor.execute("PRAGMA table_info(elFaro_producto)")
        columns = cursor.fetchall()
        print("\nEstructura de la tabla elFaro_producto:")
        for col in columns:
            print(f"  {col[1]}: {col[2]}")
        
        # Obtener muestra de datos
        cursor.execute('SELECT id, codigo_barras, precio, precio_vecino FROM elFaro_producto LIMIT 10')
        print("\nMuestra de datos:")
        for row in cursor.fetchall():
            print(f"  ID: {row[0]}, Código: {row[1]}, Precio: {row[2]}, Precio vecino: {row[3]}")
        
        # Verificar tipos de datos problemáticos
        cursor.execute('''
            SELECT id, codigo_barras, precio, precio_vecino 
            FROM elFaro_producto 
            WHERE precio IS NULL 
               OR precio_vecino IS NULL 
               OR precio = '' 
               OR precio_vecino = ''
               OR CAST(precio AS TEXT) LIKE '%.%'
               OR CAST(precio_vecino AS TEXT) LIKE '%.%'
            LIMIT 20
        ''')
        problematic = cursor.fetchall()
        print(f"\nProductos con datos problemáticos: {len(problematic)}")
        for row in problematic:
            print(f"  ID: {row[0]}, Código: {row[1]}, Precio: {row[2]}, Precio vecino: {row[3]}")
        
        conn.close()
        
    except Exception as e:
        print(f"Error al verificar la base de datos: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    check_database_status()
