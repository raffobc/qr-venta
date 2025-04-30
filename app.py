from flask import Flask, render_template, request, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
import uuid
import qrcode
import os

app = Flask(__name__)

# Configuración de la base de datos usando la variable de entorno
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv("DATABASE_URL")

# Soluciona advertencia de SQLAlchemy si usas versiones recientes
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Inicializa SQLAlchemy
db = SQLAlchemy(app)

class Cliente(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    codigos = db.relationship('CodigoQR', backref='cliente', lazy=True)

class CodigoQR(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(100), nullable=False)
    cliente_id = db.Column(db.Integer, db.ForeignKey('cliente.id'), nullable=False)
    numero_correlativo = db.Column(db.Integer, nullable=False)
    estado = db.Column(db.String(20), nullable=False, default="sin pagar")
    monto_pagado = db.Column(db.Float, nullable=True)

with app.app_context():
    db.create_all()

@app.route('/')
def index():
    clientes = Cliente.query.all()
    return render_template('index.html', clientes=clientes)

@app.route('/crear_cliente', methods=['GET', 'POST'])
def crear_cliente():
    if request.method == 'POST':
        nombre = request.form['nombre']
        nuevo_cliente = Cliente(nombre=nombre)
        db.session.add(nuevo_cliente)
        db.session.commit()
        return redirect(url_for('index'))
    return render_template('crear_cliente.html')

@app.route('/asignar_qr/<int:cliente_id>', methods=['GET', 'POST'])
def asignar_qr(cliente_id):
    cliente = Cliente.query.get_or_404(cliente_id)
    if request.method == 'POST':
        cantidad_codigos = int(request.form['cantidad'])
        ultimo_codigo = CodigoQR.query.order_by(CodigoQR.numero_correlativo.desc()).first()
        siguiente_numero = (ultimo_codigo.numero_correlativo + 1) if ultimo_codigo else 1
        os.makedirs('static/qr_codes', exist_ok=True)
        for _ in range(cantidad_codigos):
            nuevo_codigo = str(uuid.uuid4())
            nuevo_qr = CodigoQR(
                codigo=nuevo_codigo,
                cliente_id=cliente.id,
                numero_correlativo=siguiente_numero
            )
            db.session.add(nuevo_qr)

            qr = qrcode.make(nuevo_codigo)
            qr_filename = f"{str(siguiente_numero).zfill(4)}.png"
            qr_path = os.path.join('static/qr_codes', qr_filename)
            qr.save(qr_path)

            siguiente_numero += 1
        db.session.commit()
        return redirect(url_for('ver_cliente', cliente_id=cliente.id))
    return render_template('asignar_qr.html', cliente=cliente)

@app.route('/ver_cliente/<int:cliente_id>')
def ver_cliente(cliente_id):
    cliente = Cliente.query.get_or_404(cliente_id)
    return render_template('ver_cliente.html', cliente=cliente)

@app.route('/escanear', methods=['GET', 'POST'])
def escanear():
    if request.method == 'POST':
        codigo = request.form['codigo']
        qr = CodigoQR.query.filter_by(codigo=codigo).first()
        if qr:
            return redirect(url_for('ver_estado', qr_id=qr.id))
        else:
            return "Código no encontrado", 404
    return render_template('escanear.html')


@app.route('/ver_estado/<int:qr_id>', methods=['GET', 'POST'])
def ver_estado(qr_id):
    qr = CodigoQR.query.get_or_404(qr_id)

    if request.method == 'POST':
        if qr.estado == 'entregado':
            return "❌ Este código ya fue entregado. No se puede modificar.", 403

        nuevo_estado = request.form.get('estado')

        if nuevo_estado == 'pagado' and qr.estado == 'sin pagar':
            monto = request.form.get('monto')
            if monto:
                qr.monto_pagado = float(monto)
            qr.estado = 'pagado'

        elif nuevo_estado == 'entregado' and qr.estado == 'pagado':
            qr.estado = 'entregado'

        db.session.commit()
        return redirect(url_for('ver_estado', qr_id=qr.id))

    return render_template('ver_estado.html', qr=qr)

@app.route('/verificar/<numero>')
def verificar(numero):
    p = Pollada.query.filter_by(numero=numero).first()
    if not p:
        return render_template('ver_estado.html', mensaje="Código no válido ❌", boton=None)

    if p.entregado:
        return render_template('ver_estado.html', mensaje=f"N° {p.numero} ya fue ENTREGADO ✅", boton=None)

    elif not p.pagado:
        return render_template('ver_estado.html',
                               mensaje=f"N° {p.numero} NO está pagado ❌",
                               boton="Cobrar",
                               accion=url_for('cobrar', numero=numero))

    else:
        return render_template('ver_estado.html',
                               mensaje=f"N° {p.numero} está pagado ✅",
                               boton="Entregar",
                               accion=url_for('entregar', numero=numero))


@app.route('/imprimir_cliente/<int:cliente_id>')
def imprimir_cliente(cliente_id):
    cliente = Cliente.query.get_or_404(cliente_id)
    return render_template('imprimir_tarjetas.html', cliente=cliente)


@app.route('/reporte')
def reporte():
    clientes = Cliente.query.all()
    reporte_clientes = []
    total_recaudado = 0
    total_pendiente = 0
    PRECIO_POR_QR = 20.0
    for cliente in clientes:
        codigos = cliente.codigos
        pagados = [c for c in codigos if c.estado == 'pagado']
        sin_pagar = [c for c in codigos if c.estado == 'sin pagar']
        monto_pagado = sum(c.monto_pagado or 0 for c in pagados)
        monto_pendiente = len(sin_pagar) * PRECIO_POR_QR
        reporte_clientes.append({
            'nombre': cliente.nombre,
            'total_qr': len(codigos),
            'cantidad_pagados': len(pagados),
            'cantidad_sin_pagar': len(sin_pagar),
            'monto_pagado': monto_pagado,
            'monto_pendiente': monto_pendiente,
        })
        total_recaudado += monto_pagado
        total_pendiente += monto_pendiente
    return render_template('reporte.html',
                           reporte_clientes=reporte_clientes,
                           total_recaudado=total_recaudado,
                           total_pendiente=total_pendiente)

# Crear las tablas si no existen (solo al inicio)
@app.before_first_request
def crear_tablas():
    db.create_all()

# Ruta raíz de prueba
@app.route('/')
def home():
    return '¡App Flask conectada a PostgreSQL en Render!'



if __name__ == '__main__':
    app.run(debug=True)
