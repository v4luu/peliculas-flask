from flask import Flask, render_template, request, redirect, url_for
import mysql.connector
from math import ceil

app = Flask(__name__)

# Configuración de la base de datos
db_config = {
    'host': 'sakiladb.c3y2q8yamjxa.us-east-1.rds.amazonaws.com',
    'user': 'admin',
    'password': 'V4lu525.',
    'database': 'sakila'
}

# Constantes para la paginación
PER_PAGE = 10  # Películas por página
TOTAL_PELICULAS = 200  # Total de películas a mostrar

@app.route('/')
@app.route('/page/<int:page>')
def index(page=1):
    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor(dictionary=True)
    
    offset = (page - 1) * PER_PAGE
    search_query = request.args.get('q', '').strip()
    
    # Consulta base
    query = """
        SELECT 
            f.film_id, 
            f.title, 
            f.description, 
            f.release_year,
            f.length,
            f.replacement_cost,
            f.rental_rate, 
            f.rental_duration, 
            f.rating,
            GROUP_CONCAT(c.name SEPARATOR ', ') AS categories
        FROM film f
        LEFT JOIN film_category fc ON f.film_id = fc.film_id
        LEFT JOIN category c ON fc.category_id = c.category_id
        WHERE f.rental_duration > 0
    """
    
    # Agregar condición de búsqueda si existe
    params = []
    if search_query:
        query += " AND f.title LIKE %s"
        params.append(f"%{search_query}%")
    
    # Continuación de la consulta
    query += """
        GROUP BY f.film_id
        ORDER BY f.title
        LIMIT %s OFFSET %s
    """
    params.extend([PER_PAGE, offset])
    
    cursor.execute(query, params)
    peliculas = cursor.fetchall()
    
    # Calcular total de páginas (considerando búsqueda)
    count_query = "SELECT COUNT(*) as total FROM film WHERE rental_duration > 0"
    if search_query:
        count_query += " AND title LIKE %s"
        cursor.execute(count_query, (f"%{search_query}%",))
    else:
        cursor.execute(count_query)
    
    total_films = cursor.fetchone()['total']
    total_pages = ceil(min(total_films, TOTAL_PELICULAS) / PER_PAGE)
    
    cursor.close()
    conn.close()
    
    return render_template('index.html', 
                        peliculas=peliculas,
                        current_page=page,
                        total_pages=total_pages,
                        per_page=PER_PAGE,
                        TOTAL_PELICULAS=min(total_films, TOTAL_PELICULAS),
                        search_query=search_query)




@app.route('/rentar/<int:film_id>', methods=['GET', 'POST'])
def rentar(film_id):
    conn = mysql.connector.connect(**db_config)
    cursor = conn.cursor(dictionary=True)
    
    try:
        # Consulta mejorada para obtener película y disponibilidad REAL
        cursor.execute("""
            SELECT 
                f.film_id, 
                f.title,
                f.rental_rate,
                f.rental_duration,
                (
                    SELECT COUNT(*) 
                    FROM inventory i
                    WHERE i.film_id = f.film_id
                    AND NOT EXISTS (
                        SELECT 1 FROM rental r 
                        WHERE r.inventory_id = i.inventory_id
                        AND r.return_date IS NULL
                    )
                ) AS copias_disponibles
            FROM film f
            WHERE f.film_id = %s
        """, (film_id,))
        pelicula = cursor.fetchone()

        if request.method == 'POST':
            customer_id = request.form['customer_id']
            
            # Verificar cliente
            cursor.execute("SELECT first_name, last_name FROM customer WHERE customer_id = %s", (customer_id,))
            cliente = cursor.fetchone()
            
            if not cliente:
                return render_template('rentar.html',
                                    pelicula=pelicula,
                                    mensaje="Error: Cliente no existe",
                                    error=True)

            # Obtener el PRIMER inventory_id realmente disponible
            cursor.execute("""
                SELECT i.inventory_id
                FROM inventory i
                WHERE i.film_id = %s
                AND NOT EXISTS (
                    SELECT 1 FROM rental r
                    WHERE r.inventory_id = i.inventory_id
                    AND r.return_date IS NULL
                )
                LIMIT 1
                FOR UPDATE  # Bloqueamos para evitar concurrencia
            """, (film_id,))
            inventario = cursor.fetchone()
            
            if not inventario:
                return render_template('rentar.html',
                                    pelicula=pelicula,
                                    mensaje=f"No hay copias disponibles de {pelicula['title']}",
                                    error=True)

            # Registrar la nueva renta (con return_date NULL hasta devolución)
            cursor.execute("""
                INSERT INTO rental (
                    rental_date,
                    inventory_id,
                    customer_id,
                    staff_id,
                    return_date
                ) VALUES (
                    NOW(),
                    %s,
                    %s,
                    1,
                    NULL  # Se actualizará al devolver
                )
            """, (inventario['inventory_id'], customer_id))
            
            # Registrar el pago asociado
            rental_id = cursor.lastrowid
            cursor.execute("""
                INSERT INTO payment (
                    customer_id,
                    staff_id,
                    rental_id,
                    amount,
                    payment_date
                ) VALUES (%s, 1, %s, %s, NOW())
            """, (customer_id, rental_id, pelicula['rental_rate']))
            
            conn.commit()
            
            # Actualizar disponibilidad para el template
            pelicula['copias_disponibles'] -= 1
            
            return render_template('rentar.html',
                                pelicula=pelicula,
                                mensaje=f"¡Renta exitosa para {cliente['first_name']}!",
                                disponible=pelicula['copias_disponibles'] > 0)
        
        # GET request - Mostrar disponibilidad
        return render_template('rentar.html',
                            pelicula=pelicula,
                            disponible=pelicula['copias_disponibles'] > 0)
    
    except Exception as e:
        conn.rollback()
        return render_template('rentar.html',
                            pelicula=pelicula if 'pelicula' in locals() else None,
                            mensaje=f"Error: {str(e)}",
                            error=True)
    
    finally:
        cursor.close()
        conn.close()
    
    # GET request
    disponible = pelicula.get('copias_disponibles', 0) > 0
    cursor.close()
    conn.close()
    return render_template('rentar.html',
                         pelicula=pelicula,
                         film_id=film_id,
                         disponible=disponible)

if __name__ == '__main__':
    app.run(debug=True)