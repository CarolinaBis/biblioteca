"""Regras de negócio do sistema (independentes de Flask/HTTP)."""
import re
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

import bcrypt
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from models import (db, Usuario, Livro, Emprestimo, Multa, Reserva, Notificacao,
                    Configuracao, PERFIS, ESPERA, DISPONIVEL, RETIRADA, EXPIRADA, CANCELADA)

HORAS_RESERVA = 48  # EAP 4.1
DEFAULTS = {"multa_por_dia": "1.00", "prazo_emprestimo_dias": "14", "max_livros": "3"}


class ErroNegocio(Exception):
    pass


def _salvar(msg_duplicado):
    """Commit que converte violação de unicidade (duas requisições ao mesmo tempo) em erro de negócio."""
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise ErroNegocio(msg_duplicado)


def _travar_livro(livro_id):
    """Trava a linha do livro até o fim da transação (PostgreSQL; no SQLite é ignorado).
    Evita dois empréstimos/reservas do último exemplar ao mesmo tempo."""
    return db.session.query(Livro).filter_by(id=livro_id).with_for_update().first()


# ---------- configuração ----------
def get_config(chave):
    row = db.session.get(Configuracao, chave)
    return row.valor if row else DEFAULTS[chave]


def set_config(chave, valor):
    row = db.session.get(Configuracao, chave)
    if row:
        row.valor = str(valor)
    else:
        db.session.add(Configuracao(chave=chave, valor=str(valor)))
    db.session.commit()


# ---------- senha (bcrypt) ----------
def hash_senha(senha):
    return bcrypt.hashpw(senha.encode(), bcrypt.gensalt()).decode()


def verificar_senha(senha, senha_hash):
    try:
        return bcrypt.checkpw(senha.encode(), senha_hash.encode())
    except ValueError:
        return False


# ---------- notificações ----------
def notificar(usuario_id, mensagem):
    db.session.add(Notificacao(usuario_id=usuario_id, mensagem=mensagem))


# ---------- livros ----------
def normalizar_isbn(isbn):
    return re.sub(r"[\s-]", "", isbn or "")


def _validar_livro(d, livro_id=None):
    erros = []
    limpo = {k: (d.get(k) or "").strip() for k in
             ("titulo", "autores", "editora", "edicao", "isbn", "ano", "categoria",
              "localizacao", "quantidade", "sinopse")}
    limpo["isbn"] = normalizar_isbn(limpo["isbn"])
    for campo in ("titulo", "autores", "editora", "isbn", "ano", "localizacao", "quantidade"):
        if not limpo[campo]:
            erros.append(f"Campo obrigatório: {campo}.")
    try:
        limpo["ano"] = int(limpo["ano"]) if limpo["ano"] else None
        limpo["quantidade"] = int(limpo["quantidade"]) if limpo["quantidade"] else None
        if limpo["quantidade"] is not None and limpo["quantidade"] < 1:
            erros.append("A quantidade de exemplares deve ser pelo menos 1.")
    except ValueError:
        erros.append("Ano e quantidade devem ser números inteiros.")
    if limpo["isbn"]:
        q = Livro.query.filter_by(isbn=limpo["isbn"])
        if livro_id:
            q = q.filter(Livro.id != livro_id)
        if q.first():
            erros.append("Já existe um livro cadastrado com este ISBN.")
    if livro_id and isinstance(limpo.get("quantidade"), int):
        em_uso = _emprestimos_ativos(livro_id)
        if limpo["quantidade"] < em_uso:
            erros.append(f"Há {em_uso} exemplar(es) emprestado(s); a quantidade não pode ser menor.")
    return limpo, erros


def criar_livro(dados):
    limpo, erros = _validar_livro(dados)
    if erros:
        raise ErroNegocio(" ".join(erros))
    livro = Livro(**limpo)
    db.session.add(livro)
    _salvar("Já existe um livro cadastrado com este ISBN.")
    return livro


def editar_livro(livro_id, dados):
    livro = db.session.get(Livro, livro_id)
    if not livro or not livro.ativo:
        raise ErroNegocio("Livro não encontrado.")
    limpo, erros = _validar_livro(dados, livro_id)
    if erros:
        raise ErroNegocio(" ".join(erros))
    for k, v in limpo.items():
        setattr(livro, k, v)
    _salvar("Já existe um livro cadastrado com este ISBN.")
    processar_filas(livro_id)  # aumento de exemplares pode liberar a fila
    return livro


def excluir_livro(livro_id):
    """Exclusão lógica: o histórico de empréstimos é preservado."""
    livro = db.session.get(Livro, livro_id)
    if not livro or not livro.ativo:
        raise ErroNegocio("Livro não encontrado.")
    if _emprestimos_ativos(livro_id):
        raise ErroNegocio("Não é possível excluir: há exemplares emprestados.")
    livro.ativo = False
    for r in Reserva.query.filter(Reserva.livro_id == livro_id,
                                  Reserva.status.in_([ESPERA, DISPONIVEL])):
        r.status = CANCELADA
    db.session.commit()


def _filtrar_livros(titulo="", autor="", isbn="", editora="", categoria="", incluir_inativos=False):
    q = Livro.query
    if not incluir_inativos:
        q = q.filter(Livro.ativo.is_(True))
    filtros = ((Livro.titulo, titulo), (Livro.autores, autor),
               (Livro.editora, editora), (Livro.categoria, categoria))
    for coluna, valor in filtros:
        if valor and valor.strip():
            q = q.filter(coluna.ilike(f"%{valor.strip()}%"))
    if isbn and isbn.strip():
        q = q.filter(Livro.isbn.like(f"%{normalizar_isbn(isbn)}%"))
    return q.order_by(Livro.titulo)


def buscar_livros(titulo="", autor="", isbn="", editora="", categoria="",
                  incluir_inativos=False, limite=100):
    return _filtrar_livros(titulo, autor, isbn, editora, categoria, incluir_inativos).limit(limite).all()


def listar_livros(pagina=1, por_pagina=20, **filtros):
    """Sem filtros devolve o acervo completo (paginado). Retorna (livros, total, total_de_paginas)."""
    q = _filtrar_livros(**filtros)
    total = q.count()
    paginas = max(1, -(-total // por_pagina))
    pagina = min(max(pagina, 1), paginas)
    livros = q.offset((pagina - 1) * por_pagina).limit(por_pagina).all()
    return livros, total, paginas, pagina


def listar_categorias():
    linhas = (db.session.query(Livro.categoria).filter(Livro.ativo.is_(True), Livro.categoria.isnot(None),
                                                       Livro.categoria != "")
              .distinct().order_by(Livro.categoria).all())
    return [c for (c,) in linhas]


# ---------- disponibilidade (EAP 5.2) ----------
def _emprestimos_ativos(livro_id):
    return Emprestimo.query.filter_by(livro_id=livro_id, data_devolucao=None).count()


def _reservas_seguras(livro_id, agora):
    return Reserva.query.filter(Reserva.livro_id == livro_id, Reserva.status == DISPONIVEL,
                                Reserva.expira_em > agora).count()


def disponiveis(livro, agora=None):
    """Exemplares livres = total - emprestados - separados para reservas."""
    agora = agora or datetime.now()
    return livro.quantidade - _emprestimos_ativos(livro.id) - _reservas_seguras(livro.id, agora)


def mapa_disponibilidade(livros, agora=None):
    """Mesma conta de disponiveis(), mas em 2 consultas para uma lista de livros."""
    agora = agora or datetime.now()
    ids = [l.id for l in livros]
    if not ids:
        return {}
    emp = dict(db.session.query(Emprestimo.livro_id, func.count(Emprestimo.id))
               .filter(Emprestimo.livro_id.in_(ids), Emprestimo.data_devolucao.is_(None))
               .group_by(Emprestimo.livro_id).all())
    res = dict(db.session.query(Reserva.livro_id, func.count(Reserva.id))
               .filter(Reserva.livro_id.in_(ids), Reserva.status == DISPONIVEL,
                       Reserva.expira_em > agora)
               .group_by(Reserva.livro_id).all())
    return {l.id: l.quantidade - emp.get(l.id, 0) - res.get(l.id, 0) for l in livros}


# ---------- usuários ----------
def _validar_usuario(d, usuario_id=None):
    erros = []
    limpo = {k: (d.get(k) or "").strip() for k in
             ("nome", "matricula_cpf", "email", "telefone", "endereco", "perfil")}
    senha = d.get("senha") or ""
    for campo in ("nome", "matricula_cpf", "email", "perfil"):
        if not limpo[campo]:
            erros.append(f"Campo obrigatório: {campo}.")
    if limpo["email"] and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", limpo["email"]):
        erros.append("E-mail inválido.")
    if limpo["perfil"] and limpo["perfil"] not in PERFIS:
        erros.append("Perfil inválido.")
    if limpo["matricula_cpf"]:
        q = Usuario.query.filter_by(matricula_cpf=limpo["matricula_cpf"])
        if usuario_id:
            q = q.filter(Usuario.id != usuario_id)
        if q.first():
            erros.append("Já existe um usuário com esta matrícula/CPF.")
    if usuario_id is None and not senha:
        erros.append("Informe uma senha.")
    if senha and len(senha) < 6:
        erros.append("A senha deve ter pelo menos 6 caracteres.")
    return limpo, senha, erros


def criar_usuario(dados):
    limpo, senha, erros = _validar_usuario(dados)
    if erros:
        raise ErroNegocio(" ".join(erros))
    u = Usuario(**limpo, senha_hash=hash_senha(senha))
    db.session.add(u)
    _salvar("Já existe um usuário com esta matrícula/CPF.")
    return u


def editar_usuario(usuario_id, dados):
    u = db.session.get(Usuario, usuario_id)
    if not u or not u.ativo:
        raise ErroNegocio("Usuário não encontrado.")
    limpo, senha, erros = _validar_usuario(dados, usuario_id)
    if erros:
        raise ErroNegocio(" ".join(erros))
    for k, v in limpo.items():
        setattr(u, k, v)
    if senha:
        u.senha_hash = hash_senha(senha)
    _salvar("Já existe um usuário com esta matrícula/CPF.")
    return u


def excluir_usuario(usuario_id):
    """Exclusão lógica: o histórico de empréstimos e multas é preservado."""
    u = db.session.get(Usuario, usuario_id)
    if not u or not u.ativo:
        raise ErroNegocio("Usuário não encontrado.")
    if Emprestimo.query.filter_by(usuario_id=usuario_id, data_devolucao=None).count():
        raise ErroNegocio("Não é possível excluir: o usuário tem livros emprestados.")
    u.ativo = False
    afetados = set()
    for r in Reserva.query.filter(Reserva.usuario_id == usuario_id,
                                  Reserva.status.in_([ESPERA, DISPONIVEL])):
        r.status = CANCELADA
        afetados.add(r.livro_id)
    db.session.commit()
    for lid in afetados:
        processar_filas(lid)


# ---------- reservas e fila (EAP 4.1 / 4.2) ----------
def _promover(livro_id, agora):
    livro = _travar_livro(livro_id)
    if not livro or not livro.ativo:
        return
    livres = livro.quantidade - _emprestimos_ativos(livro_id) - _reservas_seguras(livro_id, agora)
    if livres <= 0:
        return
    fila = (Reserva.query.filter_by(livro_id=livro_id, status=ESPERA)
            .order_by(Reserva.criada_em, Reserva.id).all())
    for r in fila:
        if livres <= 0:
            break
        if not r.usuario.ativo:
            r.status = CANCELADA
            continue
        r.status = DISPONIVEL
        r.expira_em = agora + timedelta(hours=HORAS_RESERVA)
        notificar(r.usuario_id, f"O livro '{livro.titulo}' está disponível. "
                  f"Retire até {r.expira_em:%d/%m/%Y %H:%M}.")
        livres -= 1


def processar_filas(livro_id=None, agora=None):
    """Expira reservas vencidas e chama o próximo da fila quando há exemplar livre."""
    agora = agora or datetime.now()
    q = Reserva.query.filter(Reserva.status == DISPONIVEL, Reserva.expira_em <= agora)
    if livro_id:
        q = q.filter(Reserva.livro_id == livro_id)
    livros = {livro_id} if livro_id else set()
    expiradas = q.all()
    if not expiradas and not livro_id:
        return  # nada a fazer: evita flush/commit (ida e volta ao banco) a cada requisição
    for r in expiradas:
        r.status = EXPIRADA
        notificar(r.usuario_id, f"Sua reserva de '{r.livro.titulo}' expirou (prazo de 48h).")
        livros.add(r.livro_id)
    db.session.flush()
    for lid in sorted(livros):  # ordem estável evita deadlock entre transações
        _promover(lid, agora)
    db.session.commit()


def reservar(usuario_id, livro_id, agora=None):
    agora = agora or datetime.now()
    u = db.session.get(Usuario, usuario_id)
    livro = _travar_livro(livro_id)  # serializa reservas do mesmo livro (duplo clique, concorrência)
    if not u or not u.ativo:
        raise ErroNegocio("Usuário inválido.")
    if not livro or not livro.ativo:
        raise ErroNegocio("Livro não encontrado.")
    if Reserva.query.filter(Reserva.usuario_id == usuario_id, Reserva.livro_id == livro_id,
                            Reserva.status.in_([ESPERA, DISPONIVEL])).first():
        raise ErroNegocio("Você já possui uma reserva ativa para este livro.")
    if Emprestimo.query.filter_by(usuario_id=usuario_id, livro_id=livro_id,
                                  data_devolucao=None).first():
        raise ErroNegocio("Você já está com um exemplar deste livro.")
    r = Reserva(usuario_id=usuario_id, livro_id=livro_id, criada_em=agora, status=ESPERA)
    db.session.add(r)
    db.session.commit()
    processar_filas(livro_id, agora)  # se houver exemplar livre (e ninguém na frente), reserva na hora
    db.session.refresh(r)
    return r


def posicao_na_fila(reserva):
    if reserva.status != ESPERA:
        return None
    antes = Reserva.query.filter(
        Reserva.livro_id == reserva.livro_id, Reserva.status == ESPERA,
        (Reserva.criada_em < reserva.criada_em) |
        ((Reserva.criada_em == reserva.criada_em) & (Reserva.id < reserva.id))).count()
    return antes + 1


def cancelar_reserva(reserva_id, usuario_id):
    r = db.session.get(Reserva, reserva_id)
    if not r or r.usuario_id != usuario_id or r.status not in (ESPERA, DISPONIVEL):
        raise ErroNegocio("Reserva não encontrada.")
    r.status = CANCELADA
    db.session.commit()
    processar_filas(r.livro_id)


# ---------- empréstimos, devoluções, multas (EAP 3.x) ----------
def registrar_emprestimo(usuario_id, livro_id, agora=None):
    agora = agora or datetime.now()
    hoje = agora.date()
    u = db.session.get(Usuario, usuario_id)
    livro = db.session.get(Livro, livro_id)
    if not u or not u.ativo:
        raise ErroNegocio("Usuário não encontrado ou inativo.")
    if not livro or not livro.ativo:
        raise ErroNegocio("Livro não encontrado.")
    processar_filas(livro_id, agora)
    livro = _travar_livro(livro_id)  # a partir daqui ninguém empresta/reserva este livro até o commit
    if not livro or not livro.ativo:
        raise ErroNegocio("Livro não encontrado.")
    ativos = Emprestimo.query.filter_by(usuario_id=usuario_id, data_devolucao=None).count()
    if ativos >= int(get_config("max_livros")):
        raise ErroNegocio(f"Limite de {get_config('max_livros')} livros emprestados atingido.")

    reserva = Reserva.query.filter(Reserva.usuario_id == usuario_id,
                                   Reserva.livro_id == livro_id, Reserva.status == DISPONIVEL,
                                   Reserva.expira_em > agora).first()
    if reserva:
        reserva.status = RETIRADA  # o exemplar já estava separado para este usuário
    elif disponiveis(livro, agora) <= 0:
        raise ErroNegocio("Livro indisponível no momento.")

    emp = Emprestimo(usuario_id=usuario_id, livro_id=livro_id, data_retirada=hoje,
                     data_prevista=hoje + timedelta(days=int(get_config("prazo_emprestimo_dias"))))
    db.session.add(emp)
    db.session.commit()
    return emp


def calcular_multa(dias_atraso):
    try:
        por_dia = Decimal(get_config("multa_por_dia"))
    except InvalidOperation:
        por_dia = Decimal("1.00")
    return (por_dia * max(dias_atraso, 0)).quantize(Decimal("0.01"))


def registrar_devolucao(emprestimo_id, agora=None):
    """Retorna (emprestimo, multa|None)."""
    agora = agora or datetime.now()
    emp = db.session.get(Emprestimo, emprestimo_id)
    if not emp or emp.data_devolucao is not None:
        raise ErroNegocio("Empréstimo não encontrado ou já devolvido.")
    emp.data_devolucao = agora.date()
    multa = None
    atraso = (emp.data_devolucao - emp.data_prevista).days
    if atraso > 0:
        multa = Multa(usuario_id=emp.usuario_id, emprestimo_id=emp.id, dias_atraso=atraso,
                      valor=calcular_multa(atraso), data=emp.data_devolucao)
        db.session.add(multa)
    db.session.commit()
    processar_filas(emp.livro_id, agora)  # notifica o próximo da fila
    return emp, multa
