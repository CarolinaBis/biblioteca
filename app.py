"""Aplicação Flask: fábrica `create_app` + ponto de entrada.   Uso:  python app.py"""
import os
import time
from decimal import Decimal

from flask import Flask, g, render_template, request, session

from models import db, Usuario
import services
from services import ErroNegocio

SECRET_PADRAO = "troque-esta-chave-fora-do-ambiente-de-teste"


def inicializar_banco():
    """Cria as tabelas e o administrador inicial (senha: variável ADMIN_SENHA; padrão admin123)."""
    db.create_all()
    if Usuario.query.count() == 0:
        try:
            services.criar_usuario({
                "nome": "Administrador", "matricula_cpf": "admin",
                "email": "admin@biblioteca.local", "perfil": "Administrador",
                "senha": os.environ.get("ADMIN_SENHA", "admin123")})
        except ErroNegocio:  # outro processo criou o admin no mesmo instante
            pass


def create_app(config=None):
    app = Flask(__name__, static_folder=None)  # o CSS está embutido no base.html
    app.config.update(
        SQLALCHEMY_DATABASE_URI=os.environ.get("DATABASE_URL") or "sqlite:///biblioteca.db",
        SECRET_KEY=os.environ.get("SECRET_KEY") or SECRET_PADRAO,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )
    if config:
        app.config.update(config)

    # Fixa o driver psycopg2 (as versões novas do SQLAlchemy usariam o psycopg v3 por padrão)
    uri = app.config["SQLALCHEMY_DATABASE_URI"]
    for prefixo in ("postgres://", "postgresql://"):
        if uri.startswith(prefixo):
            uri = "postgresql+psycopg2://" + uri[len(prefixo):]
    app.config["SQLALCHEMY_DATABASE_URI"] = uri
    if uri.startswith("postgresql"):
        app.config.setdefault("SQLALCHEMY_ENGINE_OPTIONS", {"pool_pre_ping": True})  # descarta conexões mortas

    db.init_app(app)

    from views import bp
    app.register_blueprint(bp)

    varredura = {"proxima": 0.0}  # a limpeza de reservas vencidas roda no máx. a cada 30 s

    @app.before_request
    def carregar_usuario():
        g.usuario = None
        uid = session.get("uid")
        if uid:
            u = db.session.get(Usuario, uid)
            if u and u.ativo:
                g.usuario = u
            else:
                session.clear()
        if request.endpoint is not None and time.monotonic() >= varredura["proxima"]:
            varredura["proxima"] = time.monotonic() + 30   # (404/favicon e requisições seguidas não tocam no banco)
            services.processar_filas()  # expira reservas vencidas e chama a fila

    @app.after_request
    def cabecalhos_de_seguranca(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        return resp

    @app.template_filter("brl")
    def brl(v):
        v = Decimal(v or 0)
        return "R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    @app.errorhandler(403)
    def proibido(_):
        return render_template("erro.html", msg="Você não tem permissão para acessar esta página."), 403

    @app.errorhandler(404)
    def nao_encontrado(_):
        return render_template("erro.html", msg="Página não encontrada."), 404

    with app.app_context():
        inicializar_banco()
    return app


if __name__ == "__main__":
    create_app().run(debug=True)
