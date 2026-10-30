from datetime import datetime, date
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

PERFIS = ("Administrador", "Bibliotecário", "Usuário Comum")

# Status de reserva
ESPERA = "Em espera"
DISPONIVEL = "Disponível"
RETIRADA = "Retirada"
EXPIRADA = "Expirada"
CANCELADA = "Cancelada"


class Usuario(db.Model):  # EAP 2.1 / 2.2 / 2.3
    __tablename__ = "usuarios"
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(150), nullable=False)
    matricula_cpf = db.Column(db.String(30), nullable=False, unique=True, index=True)
    email = db.Column(db.String(150), nullable=False)
    telefone = db.Column(db.String(30))
    endereco = db.Column(db.String(250))
    perfil = db.Column(db.String(30), nullable=False, default="Usuário Comum")
    senha_hash = db.Column(db.String(100), nullable=False)
    data_cadastro = db.Column(db.Date, nullable=False, default=date.today)
    ativo = db.Column(db.Boolean, nullable=False, default=True)  # exclusão lógica


class Livro(db.Model):  # EAP 1.1 / 1.2 / 1.3
    __tablename__ = "livros"
    id = db.Column(db.Integer, primary_key=True)
    titulo = db.Column(db.String(250), nullable=False, index=True)
    autores = db.Column(db.String(250), nullable=False, index=True)
    editora = db.Column(db.String(150), nullable=False, index=True)
    edicao = db.Column(db.String(50))
    isbn = db.Column(db.String(20), nullable=False, unique=True, index=True)
    ano = db.Column(db.Integer, nullable=False)
    categoria = db.Column(db.String(100), index=True)
    localizacao = db.Column(db.String(100), nullable=False)
    quantidade = db.Column(db.Integer, nullable=False, default=1)  # total de exemplares
    sinopse = db.Column(db.Text)
    ativo = db.Column(db.Boolean, nullable=False, default=True)  # exclusão lógica


class Emprestimo(db.Model):  # EAP 3.1 / 3.2
    __tablename__ = "emprestimos"
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False, index=True)
    livro_id = db.Column(db.Integer, db.ForeignKey("livros.id"), nullable=False, index=True)
    data_retirada = db.Column(db.Date, nullable=False)
    data_prevista = db.Column(db.Date, nullable=False)
    data_devolucao = db.Column(db.Date)  # None = ainda emprestado
    usuario = db.relationship("Usuario")
    livro = db.relationship("Livro")


class Multa(db.Model):  # EAP 3.3
    __tablename__ = "multas"
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False, index=True)
    emprestimo_id = db.Column(db.Integer, db.ForeignKey("emprestimos.id"), nullable=False)
    dias_atraso = db.Column(db.Integer, nullable=False)
    valor = db.Column(db.Numeric(10, 2), nullable=False)
    data = db.Column(db.Date, nullable=False, default=date.today)
    emprestimo = db.relationship("Emprestimo")


class Reserva(db.Model):  # EAP 4.1 / 4.2
    __tablename__ = "reservas"
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False, index=True)
    livro_id = db.Column(db.Integer, db.ForeignKey("livros.id"), nullable=False, index=True)
    criada_em = db.Column(db.DateTime, nullable=False, default=datetime.now)
    status = db.Column(db.String(20), nullable=False, default=ESPERA)
    expira_em = db.Column(db.DateTime)  # só preenchido quando status = Disponível
    usuario = db.relationship("Usuario")
    livro = db.relationship("Livro")


class Notificacao(db.Model):  # EAP 4.2 (notificação automática)
    __tablename__ = "notificacoes"
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False, index=True)
    mensagem = db.Column(db.String(300), nullable=False)
    criada_em = db.Column(db.DateTime, nullable=False, default=datetime.now)
    lida = db.Column(db.Boolean, nullable=False, default=False)


class Configuracao(db.Model):  # EAP 3.3 (tabela de valores configurável)
    __tablename__ = "configuracoes"
    chave = db.Column(db.String(50), primary_key=True)
    valor = db.Column(db.String(100), nullable=False)
