from datetime import date
from decimal import Decimal
from functools import wraps

from flask import (Blueprint, abort, current_app, flash, g, redirect, render_template,
                   request, session, url_for)
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from models import db, Usuario, Livro, Emprestimo, Multa, Reserva, Notificacao, PERFIS, ESPERA, DISPONIVEL
import services
from services import ErroNegocio

bp = Blueprint("views", __name__)
STAFF = ("Administrador", "Bibliotecário")


def exige(*perfis):
    """Exige login e, opcionalmente, um dos perfis informados (EAP 2.2)."""
    def deco(f):
        @wraps(f)
        def wrapper(*a, **k):
            if not g.usuario:
                flash("Faça login para continuar.", "erro")
                return redirect(url_for("views.login", next=request.path))
            if perfis and g.usuario.perfil not in perfis:
                abort(403)
            return f(*a, **k)
        return wrapper
    return deco


# ---------- público: OPAC (EAP 5.1 / 5.2) ----------
@bp.route("/")
@bp.route("/opac")
def opac():
    filtros = {k: request.args.get(k, "") for k in ("titulo", "autor", "isbn", "editora", "categoria")}
    livros, total, paginas, pagina = services.listar_livros(
        pagina=request.args.get("pagina", 1, type=int), por_pagina=20, **filtros)
    return render_template("opac.html", livros=livros, disp=services.mapa_disponibilidade(livros),
                           filtros=filtros, filtrando=any(v.strip() for v in filtros.values()),
                           total=total, paginas=paginas, pagina=pagina,
                           categorias=services.listar_categorias(),
                           args={k: v for k, v in filtros.items() if v})


# ---------- autenticação (EAP 2.2) ----------
def _destino_seguro(destino):
    return destino if destino and destino.startswith("/") and not destino.startswith("//") else url_for("views.painel")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = Usuario.query.filter_by(matricula_cpf=request.form.get("matricula_cpf", "").strip()).first()
        if u and u.ativo and services.verificar_senha(request.form.get("senha", ""), u.senha_hash):
            session.clear()
            session["uid"] = u.id
            return redirect(_destino_seguro(request.args.get("next")))
        flash("Matrícula/CPF ou senha inválidos.", "erro")
    return render_template("login.html")


@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("views.opac"))


def _serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"])


@bp.route("/recuperar-senha", methods=["GET", "POST"])
def recuperar_senha():
    if request.method == "POST":
        u = Usuario.query.filter_by(matricula_cpf=request.form.get("matricula_cpf", "").strip(),
                                    email=request.form.get("email", "").strip()).first()
        if u and u.ativo:
            token = _serializer().dumps(u.id, salt="reset-senha")
            link = url_for("views.redefinir_senha", token=token, _external=True)
            # Sem servidor de e-mail neste projeto simples: o link é exibido no console.
            print(f"[RECUPERAÇÃO DE SENHA] {u.email}: {link}", flush=True)
        flash("Se os dados conferem, um link de redefinição foi gerado (válido por 1 hora). "
              "Neste projeto o link aparece no console do servidor.", "ok")
        return redirect(url_for("views.login"))
    return render_template("recuperar.html")


@bp.route("/redefinir-senha/<token>", methods=["GET", "POST"])
def redefinir_senha(token):
    try:
        uid = _serializer().loads(token, salt="reset-senha", max_age=3600)
    except (BadSignature, SignatureExpired):
        flash("Link inválido ou expirado.", "erro")
        return redirect(url_for("views.login"))
    u = db.session.get(Usuario, uid)
    if request.method == "POST":
        senha = request.form.get("senha", "")
        if len(senha) < 6:
            flash("A senha deve ter pelo menos 6 caracteres.", "erro")
        else:
            u.senha_hash = services.hash_senha(senha)
            db.session.commit()
            flash("Senha redefinida. Faça login.", "ok")
            return redirect(url_for("views.login"))
    return render_template("redefinir.html")


# ---------- minha conta (todos os perfis) ----------
@bp.route("/painel")
@exige()
def painel():
    services.processar_filas()  # situação das reservas sempre atualizada nesta tela
    uid = g.usuario.id
    emprestimos = Emprestimo.query.filter_by(usuario_id=uid, data_devolucao=None).all()
    reservas = Reserva.query.filter(Reserva.usuario_id == uid,
                                    Reserva.status.in_([ESPERA, DISPONIVEL])).all()
    multas = Multa.query.filter_by(usuario_id=uid).order_by(Multa.data.desc()).all()
    notificacoes = Notificacao.query.filter_by(usuario_id=uid).order_by(Notificacao.criada_em.desc()).limit(20).all()
    pagina = render_template("painel.html", emprestimos=emprestimos, reservas=reservas,
                             multas=multas, notificacoes=notificacoes,
                             posicao=services.posicao_na_fila)
    for n in notificacoes:
        n.lida = True
    db.session.commit()
    return pagina


@bp.route("/reservar/<int:livro_id>", methods=["POST"])
@exige()
def reservar(livro_id):
    try:
        r = services.reservar(g.usuario.id, livro_id)
        if r.status == DISPONIVEL:
            flash(f"Reserva confirmada! Retire o livro até {r.expira_em:%d/%m/%Y %H:%M} (48h).", "ok")
        else:
            flash(f"Livro indisponível: você entrou na fila de espera (posição {services.posicao_na_fila(r)}).", "ok")
    except ErroNegocio as e:
        flash(str(e), "erro")
    return redirect(request.referrer or url_for("views.painel"))


@bp.route("/reservas/<int:reserva_id>/cancelar", methods=["POST"])
@exige()
def cancelar_reserva(reserva_id):
    try:
        services.cancelar_reserva(reserva_id, g.usuario.id)
        flash("Reserva cancelada.", "ok")
    except ErroNegocio as e:
        flash(str(e), "erro")
    return redirect(url_for("views.painel"))


# ---------- livros (EAP 1.x) – Administrador e Bibliotecário ----------
@bp.route("/livros")
@exige(*STAFF)
def livros():
    filtros = {k: request.args.get(k, "") for k in ("titulo", "autor", "isbn", "editora", "categoria")}
    lista, total, paginas, pagina = services.listar_livros(
        pagina=request.args.get("pagina", 1, type=int), por_pagina=20, **filtros)
    return render_template("livros.html", livros=lista, disp=services.mapa_disponibilidade(lista),
                           filtros=filtros, total=total, paginas=paginas, pagina=pagina,
                           args={k: v for k, v in filtros.items() if v})


@bp.route("/livros/novo", methods=["GET", "POST"])
@exige(*STAFF)
def livro_novo():
    if request.method == "POST":
        try:
            services.criar_livro(request.form)
            flash("Livro cadastrado.", "ok")
            return redirect(url_for("views.livros"))
        except ErroNegocio as e:
            flash(str(e), "erro")
    return render_template("livro_form.html", livro=request.form, novo=True)


@bp.route("/livros/<int:livro_id>/editar", methods=["GET", "POST"])
@exige(*STAFF)
def livro_editar(livro_id):
    livro = db.session.get(Livro, livro_id)
    if not livro or not livro.ativo:
        abort(404)
    if request.method == "POST":
        try:
            services.editar_livro(livro_id, request.form)
            flash("Livro atualizado.", "ok")
            return redirect(url_for("views.livros"))
        except ErroNegocio as e:
            flash(str(e), "erro")
        return render_template("livro_form.html", livro=request.form, novo=False, id=livro_id)
    return render_template("livro_form.html", livro=livro, novo=False, id=livro_id)


@bp.route("/livros/<int:livro_id>/excluir", methods=["POST"])
@exige(*STAFF)
def livro_excluir(livro_id):
    try:
        services.excluir_livro(livro_id)
        flash("Livro excluído (o histórico de empréstimos foi mantido).", "ok")
    except ErroNegocio as e:
        flash(str(e), "erro")
    return redirect(url_for("views.livros"))


# ---------- usuários (EAP 2.x) – somente Administrador ----------
@bp.route("/usuarios")
@exige("Administrador")
def usuarios():
    return render_template("usuarios.html", usuarios=Usuario.query.filter_by(ativo=True).order_by(Usuario.nome).all())


@bp.route("/usuarios/novo", methods=["GET", "POST"])
@exige("Administrador")
def usuario_novo():
    if request.method == "POST":
        try:
            services.criar_usuario(request.form)
            flash("Usuário cadastrado.", "ok")
            return redirect(url_for("views.usuarios"))
        except ErroNegocio as e:
            flash(str(e), "erro")
    return render_template("usuario_form.html", u=request.form, novo=True, perfis=PERFIS)


@bp.route("/usuarios/<int:usuario_id>/editar", methods=["GET", "POST"])
@exige("Administrador")
def usuario_editar(usuario_id):
    u = db.session.get(Usuario, usuario_id)
    if not u or not u.ativo:
        abort(404)
    if request.method == "POST":
        try:
            services.editar_usuario(usuario_id, request.form)
            flash("Usuário atualizado.", "ok")
            return redirect(url_for("views.usuarios"))
        except ErroNegocio as e:
            flash(str(e), "erro")
        return render_template("usuario_form.html", u=request.form, novo=False, id=usuario_id, perfis=PERFIS)
    return render_template("usuario_form.html", u=u, novo=False, id=usuario_id, perfis=PERFIS)


@bp.route("/usuarios/<int:usuario_id>/excluir", methods=["POST"])
@exige("Administrador")
def usuario_excluir(usuario_id):
    if usuario_id == g.usuario.id:
        flash("Você não pode excluir o próprio usuário.", "erro")
    else:
        try:
            services.excluir_usuario(usuario_id)
            flash("Usuário excluído (o histórico foi mantido).", "ok")
        except ErroNegocio as e:
            flash(str(e), "erro")
    return redirect(url_for("views.usuarios"))


# ---------- empréstimos e devoluções (EAP 3.x) ----------
@bp.route("/emprestimos", methods=["GET", "POST"])
@exige(*STAFF)
def emprestimos():
    if request.method == "POST":
        u = Usuario.query.filter_by(matricula_cpf=request.form.get("matricula_cpf", "").strip(), ativo=True).first()
        livro = Livro.query.filter_by(isbn=services.normalizar_isbn(request.form.get("isbn")), ativo=True).first()
        try:
            if not u:
                raise ErroNegocio("Usuário não encontrado.")
            if not livro:
                raise ErroNegocio("Livro não encontrado (confira o ISBN).")
            emp = services.registrar_emprestimo(u.id, livro.id)
            flash(f"Empréstimo registrado. Devolução prevista: {emp.data_prevista:%d/%m/%Y}.", "ok")
        except ErroNegocio as e:
            flash(str(e), "erro")
        return redirect(url_for("views.emprestimos"))
    ativos = Emprestimo.query.filter_by(data_devolucao=None).order_by(Emprestimo.data_prevista).all()
    recentes = (Emprestimo.query.filter(Emprestimo.data_devolucao.isnot(None))
                .order_by(Emprestimo.data_devolucao.desc(), Emprestimo.id.desc()).limit(15).all())
    multas = {m.emprestimo_id: m for m in Multa.query.filter(Multa.emprestimo_id.in_([e.id for e in recentes])).all()} if recentes else {}
    return render_template("emprestimos.html", ativos=ativos, recentes=recentes, multas=multas, hoje=date.today())


@bp.route("/emprestimos/<int:emprestimo_id>/devolver", methods=["POST"])
@exige(*STAFF)
def devolver(emprestimo_id):
    try:
        emp, multa = services.registrar_devolucao(emprestimo_id)
        msg = "Devolução registrada; o livro voltou a constar como disponível."
        if multa:
            msg += f" Multa por {multa.dias_atraso} dia(s) de atraso: {services.calcular_multa(multa.dias_atraso)} (registrada no histórico do usuário)."
        flash(msg, "ok")
    except ErroNegocio as e:
        flash(str(e), "erro")
    return redirect(url_for("views.emprestimos"))


# ---------- configurações / tabela de multas (EAP 3.3) ----------
@bp.route("/configuracoes", methods=["GET", "POST"])
@exige("Administrador")
def configuracoes():
    if request.method == "POST":
        try:
            multa = request.form.get("multa_por_dia", "").replace(",", ".")
            prazo, maxl = int(request.form.get("prazo_emprestimo_dias")), int(request.form.get("max_livros"))
            if Decimal(multa) < 0 or prazo < 1 or maxl < 1:
                raise ValueError
            services.set_config("multa_por_dia", multa)
            services.set_config("prazo_emprestimo_dias", prazo)
            services.set_config("max_livros", maxl)
            flash("Configurações salvas.", "ok")
        except Exception:
            flash("Valores inválidos.", "erro")
        return redirect(url_for("views.configuracoes"))
    cfg = {k: services.get_config(k) for k in services.DEFAULTS}
    return render_template("configuracoes.html", cfg=cfg)
