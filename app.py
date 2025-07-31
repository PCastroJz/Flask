from flask import Flask, render_template, request, redirect, url_for, flash, session, make_response
from flask_login import LoginManager, login_user, logout_user, login_required, UserMixin, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import psycopg2
import os
from datetime import datetime
from urllib.parse import urlparse
from datetime import datetime, timedelta
from xhtml2pdf import pisa
from io import BytesIO

app = Flask(__name__)
app.secret_key = "clave-secreta-super-robusta-123"

# Flask-Login setup
login_manager = LoginManager(app)
login_manager.login_view = "login"

DATABASE_URL = os.environ.get("DATABASE_URL")
# DATABASE_URL = ""

def time_passed(delta):
    if not isinstance(delta, timedelta):
        return "N/A"
    
    seconds = delta.total_seconds()
    days = int(seconds // 86400)
    hours = int((seconds % 86400) // 3600)
    minutes = int((seconds % 3600) // 60)
    
    if days > 0:
        return f"{days} día{'s' if days != 1 else ''}"
    elif hours > 0:
        return f"{hours} hora{'s' if hours != 1 else ''}"
    elif minutes > 0:
        return f"{minutes} minuto{'s' if minutes != 1 else ''}"
    else:
        return "menos de 1 minuto"

# Registra el filtro en Jinja2
app.jinja_env.filters['time_passed'] = time_passed


def get_conn():
    return psycopg2.connect(DATABASE_URL, sslmode='require')


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
            c.execute(
                """
                CREATE TABLE IF NOT EXISTS usuarios (
                    id SERIAL PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL
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
                "Juan José",
            ]
            for nombre in repartidores_fijos:
                c.execute(
                    "INSERT INTO repartidores (nombre) VALUES (%s) ON CONFLICT DO NOTHING",
                    (nombre,),
                )
            # Usuario admin por defecto (solo si no existe)
            c.execute(
                "INSERT INTO usuarios (username, password_hash) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                ("admin", generate_password_hash("admin123")),
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
                SELECT r.id, r.nombre, COUNT(m.codigo), MAX(m.fecha_hora)
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
                ORDER BY MAX(m.fecha_hora) ASC
                """
            )
            return cur.fetchall()

def format_datetime(value, format='medium'):
    if format == 'full':
        format="EEEE, d 'de' MMMM 'de' y 'a las' HH:mm"
    elif format == 'medium':
        format="dd/MM/y HH:mm"
    return value.strftime(format)

app.jinja_env.filters['datetime'] = format_datetime

def get_codigos_por_repartidor(rid):
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, codigo, fecha_hora
                    FROM movimientos
                    WHERE tipo = 'salida'
                    AND repartidor_id = %s
                    AND NOT EXISTS (
                        SELECT 1 FROM movimientos m2
                        WHERE m2.tipo = 'entrada'
                        AND m2.codigo = movimientos.codigo
                        AND m2.fecha_hora > movimientos.fecha_hora
                    )
                    ORDER BY fecha_hora DESC
                    """,
                    (rid,),
                )
                return cur.fetchall()
    except Exception as e:
        print(f"Error al obtener códigos: {e}")
        return []

def get_jabas_regresadas_por_repartidor(rid):
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, codigo, fecha_hora
                    FROM movimientos
                    WHERE tipo = 'entrada'
                    AND repartidor_id = %s
                    ORDER BY fecha_hora DESC
                    """,
                    (rid,),
                )
                return cur.fetchall()
    except Exception as e:
        print(f"Error al obtener jabas regresadas: {e}")
        return []


@app.route("/")
@login_required
def index():
    cards = get_codigos_agrupados()
    return render_template("index.html", cards=cards)


@app.route("/detalle/<int:rid>")
@login_required
def detalle(rid):
    detalles = get_codigos_por_repartidor(rid)
    jabas_regresadas = get_jabas_regresadas_por_repartidor(rid)
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT nombre FROM repartidores WHERE id=%s", (rid,))
            repartidor = cur.fetchone()
    
    if not repartidor:
        flash("Repartidor no encontrado", "danger")
        return redirect(url_for("index"))
    
    return render_template(
        "detalle.html",
        detalles=detalles,
        jabas_regresadas=jabas_regresadas,
        repartidor=repartidor[0],
        now=datetime.now()
    )


@app.route("/registrar", methods=["GET", "POST"])
@login_required
def registrar():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, nombre FROM repartidores")
            repartidores = cur.fetchall()

    if request.method == "POST":
        tipo = request.form["tipo"]
        raw_codigos = request.form["codigo"]
        codigos = [c.strip().upper() for c in raw_codigos.split(",") if c.strip()]
        fecha_hora = request.form.get("fecha_hora")
        if fecha_hora:
            fecha_hora = datetime.strptime(fecha_hora, "%Y-%m-%dT%H:%M")
        else:
            fecha_hora = datetime.now()
        fecha_hora = fecha_hora.strftime("%Y-%m-%d %H:%M:%S")

        mensajes_exito = []
        mensajes_error = []

        with get_conn() as conn:
            with conn.cursor() as cur:
                if tipo == "salida":
                    repartidor_id = int(request.form["repartidor"])

                    for codigo in codigos:
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
                        mensajes_exito.append(codigo)

                elif tipo == "entrada":
                    for codigo in codigos:
                        cur.execute(
                            """
                            SELECT repartidor_id
                            FROM movimientos m1
                            WHERE m1.codigo = %s
                            AND m1.tipo = 'salida'
                            AND NOT EXISTS (
                                SELECT 1 FROM movimientos m2
                                WHERE m2.codigo = m1.codigo
                                    AND m2.tipo = 'entrada'
                                    AND m2.fecha_hora > m1.fecha_hora
                            )
                            ORDER BY m1.fecha_hora DESC
                            LIMIT 1
                        """,
                            (codigo,),
                        )
                        salida_pendiente = cur.fetchone()

                        if not salida_pendiente or salida_pendiente[0] is None:
                            mensajes_error.append(codigo)
                            continue

                        cur.execute(
                            """
                            INSERT INTO movimientos (codigo, repartidor_id, tipo, fecha_hora)
                            VALUES (%s, %s, 'entrada', %s)
                        """,
                            (codigo, salida_pendiente[0], fecha_hora),
                        )
                        mensajes_exito.append(codigo)

            conn.commit()

        if mensajes_exito:
            flash(
                f"{tipo.capitalize()} registrada para: {', '.join(mensajes_exito)}",
                "success",
            )
        if mensajes_error:
            flash(
                f"⚠️ No se pudo registrar entrada para: {', '.join(mensajes_error)} (sin salida activa)",
                "danger",
            )

        return redirect(url_for("registrar"))

    return render_template("registrar.html", repartidores=repartidores, datetime=datetime)


@app.route("/registrar-repartidor", methods=["GET", "POST"])
@login_required
def registrar_repartidor():
    if request.method == "POST":
        nombre = request.form.get("nombre")
        if not nombre:
            flash("El nombre es obligatorio", "danger")
            return redirect(url_for("registrar_repartidor"))
        with get_conn() as conn:
            with conn.cursor() as cur:
                try:
                    cur.execute("INSERT INTO repartidores (nombre) VALUES (%s)", (nombre.strip(),))
                    conn.commit()
                    flash("Repartidor registrado exitosamente", "success")
                except Exception as e:
                    flash(f"Error: {e}", "danger")
        return redirect(url_for("registrar_repartidor"))
    return render_template("registrar_repartidor.html")


# User model for Flask-Login
class Usuario(UserMixin):
    def __init__(self, id, username, password_hash):
        self.id = id
        self.username = username
        self.password_hash = password_hash

    @staticmethod
    def get_by_username(username):
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id, username, password_hash FROM usuarios WHERE username=%s", (username,))
                row = cur.fetchone()
                if row:
                    return Usuario(*row)
        return None

    @staticmethod
    def get_by_id(user_id):
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id, username, password_hash FROM usuarios WHERE id=%s", (user_id,))
                row = cur.fetchone()
                if row:
                    return Usuario(*row)
        return None


@login_manager.user_loader
def load_user(user_id):
    return Usuario.get_by_id(user_id)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        user = Usuario.get_by_username(username)
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            flash("Inicio de sesión exitoso", "success")
            return redirect(url_for("index"))
        else:
            flash("Usuario o contraseña incorrectos", "danger")
    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Sesión cerrada", "info")
    return redirect(url_for("login"))


@app.route("/reporte", methods=["GET", "POST"])
@login_required
def reporte():
    from datetime import datetime
    fecha = request.form.get("fecha")
    rid = request.form.get("repartidor")
    repartidores = []
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, nombre FROM repartidores")
            repartidores = cur.fetchall()
            if not fecha:
                fecha = datetime.now().strftime("%Y-%m-%d")
            # Jabas llevadas
            cur.execute("""
                SELECT r.nombre, COUNT(m.id)
                FROM repartidores r
                LEFT JOIN movimientos m ON r.id = m.repartidor_id
                AND m.tipo = 'salida'
                AND DATE(m.fecha_hora) = %s
                GROUP BY r.nombre
            """, (fecha,))
            llevadas = cur.fetchall()
            cur.execute("""
                SELECT r.nombre, COUNT(m.id)
                FROM repartidores r
                LEFT JOIN movimientos m ON r.id = m.repartidor_id
                AND m.tipo = 'entrada'
                AND DATE(m.fecha_hora) = %s
                GROUP BY r.nombre
            """, (fecha,))
            devueltas = cur.fetchall()
            cur.execute("""
                SELECT r.nombre, COUNT(m.codigo)
                FROM repartidores r
                LEFT JOIN movimientos m ON r.id = m.repartidor_id
                WHERE m.tipo = 'salida'
                AND NOT EXISTS (
                    SELECT 1 FROM movimientos m2
                    WHERE m2.tipo = 'entrada'
                    AND m2.codigo = m.codigo
                    AND m2.fecha_hora > m.fecha_hora
                )
                AND DATE(m.fecha_hora) = %s
                GROUP BY r.nombre
            """, (fecha,))
            pendientes = cur.fetchall()
            movimientos_detalle = []
            if rid:
                cur.execute("""
                    SELECT r.nombre, m.codigo, m.tipo, m.fecha_hora
                    FROM repartidores r
                    JOIN movimientos m ON r.id = m.repartidor_id
                    WHERE DATE(m.fecha_hora) = %s AND r.id = %s
                    ORDER BY m.fecha_hora ASC
                """, (fecha, rid))
                movimientos_detalle = cur.fetchall()
            else:
                cur.execute("""
                    SELECT r.nombre, m.codigo, m.tipo, m.fecha_hora
                    FROM repartidores r
                    JOIN movimientos m ON r.id = m.repartidor_id
                    WHERE DATE(m.fecha_hora) = %s
                    ORDER BY r.nombre, m.fecha_hora ASC
                """, (fecha,))
                movimientos_detalle = cur.fetchall()
    return render_template("reporte.html", fecha=fecha, llevadas=llevadas, devueltas=devueltas, pendientes=pendientes, movimientos_detalle=movimientos_detalle, repartidores=repartidores, rid=rid)

@app.route("/reporte/pdf", methods=["POST"])
@login_required
def reporte_pdf():
    fecha = request.form.get("fecha")
    rid = request.form.get("repartidor")
    repartidores = []
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, nombre FROM repartidores")
            repartidores = cur.fetchall()
            cur.execute("""
                SELECT r.nombre, COUNT(m.id)
                FROM repartidores r
                LEFT JOIN movimientos m ON r.id = m.repartidor_id
                AND m.tipo = 'salida'
                AND DATE(m.fecha_hora) = %s
                GROUP BY r.nombre
            """, (fecha,))
            llevadas = cur.fetchall()
            cur.execute("""
                SELECT r.nombre, COUNT(m.id)
                FROM repartidores r
                LEFT JOIN movimientos m ON r.id = m.repartidor_id
                AND m.tipo = 'entrada'
                AND DATE(m.fecha_hora) = %s
                GROUP BY r.nombre
            """, (fecha,))
            devueltas = cur.fetchall()
            cur.execute("""
                SELECT r.nombre, COUNT(m.codigo)
                FROM repartidores r
                LEFT JOIN movimientos m ON r.id = m.repartidor_id
                WHERE m.tipo = 'salida'
                AND NOT EXISTS (
                    SELECT 1 FROM movimientos m2
                    WHERE m2.tipo = 'entrada'
                    AND m2.codigo = m.codigo
                    AND m2.fecha_hora > m.fecha_hora
                )
                AND DATE(m.fecha_hora) = %s
                GROUP BY r.nombre
            """, (fecha,))
            pendientes = cur.fetchall()
            movimientos_detalle = []
            if rid:
                cur.execute("""
                    SELECT r.nombre, m.codigo, m.tipo, m.fecha_hora
                    FROM repartidores r
                    JOIN movimientos m ON r.id = m.repartidor_id
                    WHERE DATE(m.fecha_hora) = %s AND r.id = %s
                    ORDER BY m.fecha_hora ASC
                """, (fecha, rid))
                movimientos_detalle = cur.fetchall()
            else:
                cur.execute("""
                    SELECT r.nombre, m.codigo, m.tipo, m.fecha_hora
                    FROM repartidores r
                    JOIN movimientos m ON r.id = m.repartidor_id
                    WHERE DATE(m.fecha_hora) = %s
                    ORDER BY r.nombre, m.fecha_hora ASC
                """, (fecha,))
                movimientos_detalle = cur.fetchall()
    html = render_template("reporte_pdf.html", fecha=fecha, llevadas=llevadas, devueltas=devueltas, pendientes=pendientes, movimientos_detalle=movimientos_detalle, repartidores=repartidores, rid=rid)
    pdf = BytesIO()
    pisa_status = pisa.CreatePDF(html, dest=pdf)
    if pisa_status.err:
        flash("Error al generar el PDF", "danger")
        return redirect(url_for("reporte"))
    pdf.seek(0)
    response = make_response(pdf.read())
    response.headers["Content-Type"] = "application/pdf"
    response.headers["Content-Disposition"] = f"attachment; filename=reporte_{fecha}.pdf"
    return response

@app.route('/editar-movimiento/<int:id>', methods=['GET', 'POST'])
@login_required
def editar_movimiento(id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT tipo, fecha_hora, repartidor_id, codigo FROM movimientos WHERE id = %s", (id,))
            mov = cur.fetchone()
    if not mov:
        flash('Movimiento no encontrado.', 'danger')
        return redirect(url_for('index'))
    if request.method == 'POST':
        tipo = request.form['tipo']
        fecha_hora = request.form['fecha_hora']
        repartidor = request.form.get('repartidor')
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE movimientos SET tipo=%s, fecha_hora=%s, repartidor_id=%s WHERE id=%s",
                            (tipo, fecha_hora, repartidor, id))
                conn.commit()
        flash('Movimiento actualizado correctamente.', 'success')
        return redirect(url_for('detalle', rid=repartidor))
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, nombre FROM repartidores")
            repartidores = cur.fetchall()
    return render_template('editar_movimiento.html', id=id, mov=mov, repartidores=repartidores)

@app.route('/eliminar-movimiento/<int:id>', methods=['POST'])
@login_required
def eliminar_movimiento(id):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM movimientos WHERE id = %s", (id,))
            conn.commit()
    flash('Movimiento eliminado correctamente.', 'success')
    return redirect(request.referrer or url_for('index'))

# Llamar init_db al iniciar el contenedor (incluso fuera del __main__)
init_db()

if __name__ == "__main__":
    app.run(debug=True)
