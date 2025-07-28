from flask import Flask, render_template, request, redirect, url_for
import sqlite3
from datetime import datetime
import os
from flask import flash

app = Flask(__name__)
app.secret_key = 'clave-secreta-super-robusta-123'
DB = os.path.join(os.path.dirname(__file__), "movimientos.db")


# Inicializar BD
def init_db():
    with sqlite3.connect(DB) as conn:
        c = conn.cursor()
        # Tabla de repartidores
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS repartidores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT UNIQUE NOT NULL
            )
        """
        )
        # Tabla de movimientos
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS movimientos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                codigo TEXT,
                repartidor_id INTEGER,
                tipo TEXT,
                fecha_hora TEXT,
                FOREIGN KEY (repartidor_id) REFERENCES repartidores(id)
            )
        """
        )
        # Insertar repartidores si no existen
        repartidores_fijos = [
            "Onofre",
            "Philis",
            "Rafa",
            "Isaías",
            "Josué",
            "Pacheco",
            "Mike",
            "Zamorano",
        ]
        for nombre in repartidores_fijos:
            c.execute(
                "INSERT OR IGNORE INTO repartidores (nombre) VALUES (?)", (nombre,)
            )


def get_repartidores():
    with sqlite3.connect(DB) as conn:
        return conn.execute("SELECT id, nombre FROM repartidores").fetchall()


def get_codigos_agrupados():
    with sqlite3.connect(DB) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT r.id, r.nombre, COUNT(m.codigo)
            FROM repartidores r
            LEFT JOIN movimientos m ON r.id = m.repartidor_id
            WHERE m.tipo = 'salida'
            AND NOT EXISTS (
                SELECT 1 FROM movimientos m2
                WHERE m2.tipo = 'entrada'
                AND m2.codigo = m.codigo
                AND m2.fecha_hora > m.fecha_hora
            )
            GROUP BY r.id, r.nombre
        """
        )
        return cur.fetchall()


# Obtener detalles de códigos activos para un repartidor
def get_codigos_por_repartidor(rid):
    with sqlite3.connect(DB) as conn:
        return conn.execute(
            """
            SELECT codigo, fecha_hora
            FROM movimientos
            WHERE tipo = 'salida'
            AND repartidor_id = ?
            AND NOT EXISTS (
                SELECT 1 FROM movimientos m2
                WHERE m2.tipo = 'entrada'
                AND m2.codigo = movimientos.codigo
                AND m2.fecha_hora > movimientos.fecha_hora
            )
        """,
            (rid,),
        ).fetchall()


@app.route("/")
def index():
    cards = get_codigos_agrupados()
    return render_template("index.html", cards=cards)


@app.route("/detalle/<int:rid>")
def detalle(rid):
    detalles = get_codigos_por_repartidor(rid)
    with sqlite3.connect(DB) as conn:
        repartidor = conn.execute(
            "SELECT nombre FROM repartidores WHERE id=?", (rid,)
        ).fetchone()
    return render_template("detalle.html", detalles=detalles, repartidor=repartidor[0])


@app.route("/registrar", methods=["GET", "POST"])
def registrar():
    repartidores = get_repartidores()

    if request.method == "POST":
        tipo = request.form["tipo"]
        raw_codigos = request.form['codigo']
        codigos = [c.strip().upper() for c in raw_codigos.split(',') if c.strip()]
        
        fecha_hora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with sqlite3.connect(DB) as conn:
            cur = conn.cursor()

            if tipo == "salida":
                repartidor_id = int(request.form["repartidor"])

                for codigo in codigos:
                    # Verificar salida sin entrada
                    cur.execute('''
                        SELECT repartidor_id, MAX(fecha_hora)
                        FROM movimientos
                        WHERE codigo = ? AND tipo = 'salida'
                        AND NOT EXISTS (
                            SELECT 1 FROM movimientos m2
                            WHERE m2.codigo = movimientos.codigo
                            AND m2.tipo = 'entrada'
                            AND m2.fecha_hora > movimientos.fecha_hora
                        )
                    ''', (codigo,))
                    salida_pendiente = cur.fetchone()

                    if salida_pendiente and salida_pendiente[0] is not None:
                        # Registrar entrada automática previa
                        cur.execute('''
                            INSERT INTO movimientos (codigo, repartidor_id, tipo, fecha_hora)
                            VALUES (?, ?, 'entrada', ?)
                        ''', (codigo, salida_pendiente[0], fecha_hora))

                    # Registrar salida actual
                    cur.execute('''
                        INSERT INTO movimientos (codigo, repartidor_id, tipo, fecha_hora)
                        VALUES (?, ?, 'salida', ?)
                    ''', (codigo, repartidor_id, fecha_hora))

                    flash(f'Salida registrada para {codigo}.', 'success')

            elif tipo == "entrada":
                # Buscar salida activa
                for codigo in codigos:
                    cur.execute('''
                        SELECT repartidor_id, MAX(fecha_hora)
                        FROM movimientos
                        WHERE codigo = ? AND tipo = 'salida'
                        AND NOT EXISTS (
                            SELECT 1 FROM movimientos m2
                            WHERE m2.codigo = movimientos.codigo
                            AND m2.tipo = 'entrada'
                            AND m2.fecha_hora > movimientos.fecha_hora
                        )
                    ''', (codigo,))
                    salida_pendiente = cur.fetchone()

                    if not salida_pendiente or salida_pendiente[0] is None:
                        flash(f'⚠️ No se puede registrar entrada para {codigo} (no tiene salida activa).', 'danger')
                        continue

                    cur.execute('''
                        INSERT INTO movimientos (codigo, repartidor_id, tipo, fecha_hora)
                        VALUES (?, ?, 'entrada', ?)
                    ''', (codigo, salida_pendiente[0], fecha_hora))

                    flash(f'Entrada registrada para {codigo}.', 'success')

        return redirect(url_for("registrar"))

    return render_template("registrar.html", repartidores=repartidores)


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
