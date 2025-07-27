import sqlite3
import re

# Ruta absoluta a la base de datos
DB_PATH = 'db.sqlite3'
# Nombre de la tabla de productos (ajusta si tu tabla tiene prefijo o nombre distinto)
TABLE_NAME = 'elFaro_producto'

# Intenta convertir a float, si falla es corrupto
def is_invalid_decimal(value):
    # Considera inválido si es None, vacío, o no convertible a float
    if value is None:
        return True
    value_str = str(value).strip()
    if value_str == '':
        return True
    try:
        float(value_str)
        return False
    except Exception:
        return True

def show_and_clean_invalid_products():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(f"SELECT id, precio, precio_vecino FROM {TABLE_NAME}")
    rows = c.fetchall()
    to_delete = []
    for row in rows:
        id_, precio, precio_vecino = row
        if is_invalid_decimal(precio) or is_invalid_decimal(precio_vecino):
            print(f"ID: {id_}, precio: {precio}, precio_vecino: {precio_vecino}")
            to_delete.append(id_)
    if to_delete:
        c.executemany(f"DELETE FROM {TABLE_NAME} WHERE id = ?", [(i,) for i in to_delete])
        print(f"Eliminados {len(to_delete)} productos corruptos (NULL, vacíos o no numéricos).")
    else:
        print("No se encontraron productos corruptos.")
    conn.commit()
    conn.close()

def show_all_precio_values():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(f"SELECT id, precio, precio_vecino FROM {TABLE_NAME}")
    rows = c.fetchall()
    print("Listado de todos los productos y sus valores de precio y precio_vecino:")
    for row in rows:
        id_, precio, precio_vecino = row
        print(f"ID: {id_}, precio: '{precio}', precio_vecino: '{precio_vecino}'")
    conn.close()

def eliminar_decimales():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(f"SELECT id, precio, precio_vecino FROM {TABLE_NAME}")
    rows = c.fetchall()
    to_delete = []
    for row in rows:
        id_, precio, precio_vecino = row
        # Eliminar si precio o precio_vecino contienen un punto decimal
        if (isinstance(precio, str) and '.' in precio) or (isinstance(precio_vecino, str) and '.' in precio_vecino):
            print(f"ID: {id_}, precio: '{precio}', precio_vecino: '{precio_vecino}' (decimal detectado)")
            to_delete.append(id_)
        # También eliminar si son float y no son enteros
        try:
            if float(precio) != int(float(precio)):
                print(f"ID: {id_}, precio: '{precio}' (no entero)")
                to_delete.append(id_)
            if precio_vecino is not None and float(precio_vecino) != int(float(precio_vecino)):
                print(f"ID: {id_}, precio_vecino: '{precio_vecino}' (no entero)")
                to_delete.append(id_)
        except Exception:
            pass
    # Eliminar duplicados
    to_delete = list(set(to_delete))
    if to_delete:
        c.executemany(f"DELETE FROM {TABLE_NAME} WHERE id = ?", [(i,) for i in to_delete])
        print(f"Eliminados {len(to_delete)} productos con decimales en precio o precio_vecino.")
    else:
        print("No se encontraron productos con decimales.")
    conn.commit()
    conn.close()

def eliminar_todos_productos_decimales():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Eliminar productos donde precio o precio_vecino contengan punto decimal
    c.execute(f"DELETE FROM {TABLE_NAME} WHERE precio LIKE '%.%' OR precio_vecino LIKE '%.%'")
    eliminados1 = c.rowcount
    
    # Eliminar productos donde precio o precio_vecino no sean números enteros válidos
    c.execute(f"SELECT id FROM {TABLE_NAME}")
    rows = c.fetchall()
    to_delete = []
    
    for row in rows:
        id_ = row[0]
        try:
            c.execute(f"SELECT precio, precio_vecino FROM {TABLE_NAME} WHERE id = ?", (id_,))
            precio_row = c.fetchone()
            if precio_row:
                precio, precio_vecino = precio_row
                # Si precio no es un entero válido
                try:
                    if precio is not None:
                        float_val = float(precio)
                        if float_val != int(float_val):
                            to_delete.append(id_)
                            continue
                except:
                    to_delete.append(id_)
                    continue
                
                # Si precio_vecino no es un entero válido
                try:
                    if precio_vecino is not None:
                        float_val = float(precio_vecino)
                        if float_val != int(float_val):
                            to_delete.append(id_)
                            continue
                except:
                    to_delete.append(id_)
                    continue
        except:
            to_delete.append(id_)
    
    if to_delete:
        c.executemany(f"DELETE FROM {TABLE_NAME} WHERE id = ?", [(i,) for i in to_delete])
        eliminados2 = len(to_delete)
    else:
        eliminados2 = 0
    
    total_eliminados = eliminados1 + eliminados2
    print(f"Eliminados {total_eliminados} productos con decimales ({eliminados1} con LIKE, {eliminados2} validación adicional).")
    
    conn.commit()
    conn.close()

if __name__ == '__main__':
    show_and_clean_invalid_products()
    show_all_precio_values()
    eliminar_decimales()
    eliminar_todos_productos_decimales()
