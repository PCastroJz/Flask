from flask import Flask, render_template, request, redirect, url_for, flash
import psycopg2
import os
from datetime import datetime
from urllib.parse import urlparse
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = "clave-secreta-super-robusta-123"

DATABASE_URL = os.environ.get("DATABASE_URL")

print("Conectando a:", DATABASE_URL)


def get_conn():
    return psycopg2.connect(DATABASE_URL, sslmode="require")


def init_db():
    with get_conn() as conn:
        with conn.cursor() as c:
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS repartidores (
                    id SERIAL PRIMARY KEY,
                    nombre TEXT UNIQUE NOT NULL
                );
            """
            )
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS movimientos (
                    id SERIAL PRIMARY KEY,
                    codigo TEXT,
                    repartidor_id INTEGER REFERENCES repartidores(id),
                    tipo TEXT,
                    fecha_hora TIMESTAMP
                );
            """
            )
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
                    "INSERT INTO repartidores (nombre) VALUES (%s) ON CONFLICT DO NOTHING",
                    (nombre,),
                )
        conn.commit()


def get_repartidores():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, nombre FROM repartidores")
            return cur.fetchall()


def get_codigos_agrupados():
    with get_conn() as conn:
        with conn.cursor() as cur:
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


def get_codigos_por_repartidor(rid):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT codigo, fecha_hora
                FROM movimientos
                WHERE tipo = 'salida'
                AND repartidor_id = %s
                AND NOT EXISTS (
                    SELECT 1 FROM movimientos m2
                    WHERE m2.tipo = 'entrada'
                    AND m2.codigo = movimientos.codigo
                    AND m2.fecha_hora > movimientos.fecha_hora
                )
            """,
                (rid,),
            )
            return cur.fetchall()


@app.route("/")
def index():
    cards = get_codigos_agrupados()
    return render_template("index.html", cards=cards)


@app.route("/detalle/<int:rid>")
def detalle(rid):
    detalles = get_codigos_por_repartidor(rid)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT nombre FROM repartidores WHERE id=%s", (rid,))
            repartidor = cur.fetchone()
    return render_template("detalle.html", detalles=detalles, repartidor=repartidor[0])


@app.route("/registrar", methods=["GET", "POST"])
def registrar():
    repartidores = get_repartidores()

    if request.method == "POST":
        tipo = request.form["tipo"]
        raw_codigos = request.form["codigo"]
        codigos = [c.strip().upper() for c in raw_codigos.split(",") if c.strip()]
        fecha_hora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with get_conn() as conn:
            with conn.cursor() as cur:
                if tipo == "salida":
                    repartidor_id = int(request.form["repartidor"])

                    for codigo in codigos:
                        # Verificar salida sin entrada
                        cur.execute(
                            """
                            SELECT repartidor_id
                            FROM movimientos
                            WHERE codigo = %s AND tipo = 'salida'
                            AND NOT EXISTS (
                                SELECT 1 FROM movimientos m2
                                WHERE m2.codigo = movimientos.codigo
                                AND m2.tipo = 'entrada'
                                AND m2.fecha_hora > movimientos.fecha_hora
                            )
                            ORDER BY fecha_hora DESC
                            LIMIT 1
                        """,
                            (codigo,),
                        )
                        salida_pendiente = cur.fetchone()

                        if salida_pendiente and salida_pendiente[0] is not None:
                            cur.execute(
                                """
                                INSERT INTO movimientos (codigo, repartidor_id, tipo, fecha_hora)
                                VALUES (%s, %s, 'entrada', %s)
                            """,
                                (codigo, salida_pendiente[0], fecha_hora),
                            )

                        cur.execute(
                            """
                            INSERT INTO movimientos (codigo, repartidor_id, tipo, fecha_hora)
                            VALUES (%s, %s, 'salida', %s)
                        """,
                            (codigo, repartidor_id, fecha_hora),
                        )
                        flash(f"Salida registrada para {codigo}.", "success")

                elif tipo == "entrada":
                    for codigo in codigos:
                        cur.execute(
                            """
                            SELECT repartidor_id, MAX(fecha_hora)
                            FROM movimientos
                            WHERE codigo = %s AND tipo = 'salida'
                            AND NOT EXISTS (
                                SELECT 1 FROM movimientos m2
                                WHERE m2.codigo = movimientos.codigo
                                AND m2.tipo = 'entrada'
                                AND m2.fecha_hora > movimientos.fecha_hora
                            )
                        """,
                            (codigo,),
                        )
                        salida_pendiente = cur.fetchone()

                        if not salida_pendiente or salida_pendiente[0] is None:
                            flash(
                                f"⚠️ No se puede registrar entrada para {codigo} (no tiene salida activa).",
                                "danger",
                            )
                            continue

                        cur.execute(
                            """
                            INSERT INTO movimientos (codigo, repartidor_id, tipo, fecha_hora)
                            VALUES (%s, %s, 'entrada', %s)
                        """,
                            (codigo, salida_pendiente[0], fecha_hora),
                        )
                        flash(f"Entrada registrada para {codigo}.", "success")

            conn.commit()
        return redirect(url_for("registrar"))

    return render_template("registrar.html", repartidores=repartidores)


# Llamar init_db al iniciar el contenedor (incluso fuera del __main__)
init_db()

if __name__ == "__main__":
    app.run(debug=True)
