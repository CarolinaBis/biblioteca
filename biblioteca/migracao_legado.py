"""Migração de dados do sistema legado (JSON) para o banco novo (EAP 6.1).

Uso:  python migracao_legado.py caminho/do/legado.json
      python migracao_legado.py --gerar-exemplo   (cria legado_exemplo.json para testar)

Formato esperado (ASSUMIDO – ajuste os apelidos em ALIAS se o legado for diferente):
  {"livros":   [{"titulo":..., "autor":..., "editora":..., "isbn":..., "ano":...,
                 "localizacao":..., "quantidade":..., ...}],
   "usuarios": [{"nome":..., "matricula":..., "email":..., ...}]}

Regras:
- registros inválidos ou duplicados (no arquivo ou já no banco) NÃO são importados e ficam no relatório;
- usuários migrados recebem senha aleatória (precisam usar "Esqueci minha senha");
- é gerado um relatório de migração em relatorio_migracao_AAAAMMDD_HHMMSS.txt.
"""
import json
import secrets
import sys
from datetime import datetime

from models import db
import services
from services import ErroNegocio

# Exemplo do formato aceito (gerado com:  python migracao_legado.py --gerar-exemplo)
EXEMPLO = {
  "livros": [
    {
      "titulo": "Dom Casmurro",
      "autor": "Machado de Assis",
      "editora": "Editora A",
      "isbn": "978-85-359-0277-5",
      "ano": 1899,
      "localizacao": "A1-01",
      "quantidade": 2,
      "categoria": "Romance"
    },
    {
      "titulo": "Gestão de Projetos",
      "autor": "PMI",
      "editora": "PMI Press",
      "isbn": "978-1-62825-664-2",
      "ano": 2021,
      "localizacao": "B2-05",
      "quantidade": 1,
      "categoria": "Gestão"
    },
    {
      "titulo": "Dom Casmurro (duplicado)",
      "autor": "Machado de Assis",
      "editora": "Editora A",
      "isbn": "9788535902775",
      "ano": 1899,
      "localizacao": "A1-02",
      "quantidade": 1
    }
  ],
  "usuarios": [
    {
      "nome": "Maria Souza",
      "matricula": "2024001",
      "email": "maria@exemplo.com",
      "telefone": "16 99999-0001"
    },
    {
      "nome": "João Lima",
      "cpf": "123.456.789-00",
      "email": "joao@exemplo.com"
    },
    {
      "nome": "Sem Email",
      "matricula": "2024003",
      "email": ""
    }
  ]
}


# nome no novo sistema -> possíveis nomes no legado
ALIAS = {
    "titulo": ("titulo", "título", "title"),
    "autores": ("autores", "autor", "author"),
    "editora": ("editora", "publisher"),
    "edicao": ("edicao", "edição"),
    "isbn": ("isbn",),
    "ano": ("ano", "ano_publicacao", "year"),
    "categoria": ("categoria", "category"),
    "localizacao": ("localizacao", "localização", "prateleira"),
    "quantidade": ("quantidade", "exemplares", "qtd"),
    "sinopse": ("sinopse",),
    "nome": ("nome", "name"),
    "matricula_cpf": ("matricula_cpf", "matricula", "matrícula", "cpf"),
    "email": ("email", "e-mail"),
    "telefone": ("telefone", "fone"),
    "endereco": ("endereco", "endereço"),
    "perfil": ("perfil",),
}


def _pegar(registro, campo):
    for nome in ALIAS[campo]:
        if nome in registro and registro[nome] is not None:
            return str(registro[nome])
    return ""


def migrar(caminho):
    with open(caminho, encoding="utf-8") as f:
        dados = json.load(f)
    livros_json = dados.get("livros", [])
    usuarios_json = dados.get("usuarios", [])
    rel = {"livros": {"lidos": len(livros_json), "ok": 0, "rejeitados": []},
           "usuarios": {"lidos": len(usuarios_json), "ok": 0, "rejeitados": []}}

    for i, reg in enumerate(livros_json, 1):
        d = {c: _pegar(reg, c) for c in ("titulo", "autores", "editora", "edicao", "isbn", "ano",
                                         "categoria", "localizacao", "quantidade", "sinopse")}
        d["quantidade"] = d["quantidade"] or "1"  # legado sem quantidade = 1 exemplar (ASSUMIDO)
        try:
            services.criar_livro(d)  # mesmas validações do cadastro (ISBN duplicado, obrigatórios)
            rel["livros"]["ok"] += 1
        except ErroNegocio as e:
            db.session.rollback()
            rel["livros"]["rejeitados"].append(f"registro #{i} (ISBN {d['isbn'] or '-'}): {e}")

    for i, reg in enumerate(usuarios_json, 1):
        d = {c: _pegar(reg, c) for c in ("nome", "matricula_cpf", "email", "telefone", "endereco", "perfil")}
        d["perfil"] = d["perfil"] if d["perfil"] in services.PERFIS else "Usuário Comum"
        d["senha"] = secrets.token_urlsafe(12)  # senha aleatória; usuário usa "Esqueci minha senha"
        try:
            services.criar_usuario(d)
            rel["usuarios"]["ok"] += 1
        except ErroNegocio as e:
            db.session.rollback()
            rel["usuarios"]["rejeitados"].append(f"registro #{i} ({d['matricula_cpf'] or '-'}): {e}")
    return rel


def gerar_relatorio(rel, origem):
    linhas = [f"RELATÓRIO DE MIGRAÇÃO – {datetime.now():%d/%m/%Y %H:%M:%S}", f"Origem: {origem}", ""]
    integro = True
    for chave, titulo in (("livros", "LIVROS"), ("usuarios", "USUÁRIOS")):
        r = rel[chave]
        rej = len(r["rejeitados"])
        fechou = r["lidos"] == r["ok"] + rej  # nenhum registro some sem explicação
        integro &= fechou
        linhas += [titulo, f"  Lidos do legado : {r['lidos']}", f"  Importados      : {r['ok']}",
                   f"  Rejeitados      : {rej}",
                   f"  Conferência     : lidos = importados + rejeitados -> {'OK' if fechou else 'FALHOU'}"]
        linhas += [f"    - {m}" for m in r["rejeitados"]]
        linhas.append("")
    total_rej = sum(len(rel[k]["rejeitados"]) for k in rel)
    linhas.append("RESULTADO: " + ("100% dos registros migrados, sem perda ou duplicação."
                                   if integro and total_rej == 0 else
                                   "migração concluída COM PENDÊNCIAS (veja os rejeitados acima)."))
    return "\n".join(linhas)


def gerar_exemplo(caminho="legado_exemplo.json"):
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(EXEMPLO, f, ensure_ascii=False, indent=2)
    return caminho


if __name__ == "__main__":
    if sys.argv[1:] == ["--gerar-exemplo"]:
        print("Arquivo de exemplo criado:", gerar_exemplo())
        sys.exit(0)
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    from app import create_app

    with create_app().app_context():
        relatorio = gerar_relatorio(migrar(sys.argv[1]), sys.argv[1])
    nome = f"relatorio_migracao_{datetime.now():%Y%m%d_%H%M%S}.txt"
    with open(nome, "w", encoding="utf-8") as f:
        f.write(relatorio)
    print(relatorio)
    print(f"\nRelatório salvo em {nome}")
