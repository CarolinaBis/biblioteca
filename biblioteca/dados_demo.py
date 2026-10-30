"""Dados de demonstração (tudo FICTÍCIO): catálogo mock, usuários de exemplo e 2 empréstimos.
Uso (opcional, para testar localmente):
    python dados_demo.py                   -> usuários de exemplo + catálogo + 2 empréstimos
    python dados_demo.py --somente-livros  -> só o catálogo
Para popular um PostgreSQL, rode com DATABASE_URL apontando para ele.
(titulo, autores, categoria, ano, localizacao, quantidade) — ISBNs, editoras, anos e localizações são inventados."""
from datetime import datetime, timedelta

from models import Livro, Usuario, Emprestimo
import services

# Os 4 primeiros mantêm os ISBNs usados nos exemplos do README.
FIXOS = {
    "Dom Casmurro": "9788535902775",
    "Engenharia de Software": "9788579361081",
    "Gerenciamento de Projetos": "9781628256642",
    "O Cortiço": "9788508040292",
}

LIVROS = [
    # Literatura brasileira
    ("Dom Casmurro", "Machado de Assis", "Literatura Brasileira", 1899, "A1-01", 2),
    ("Memórias Póstumas de Brás Cubas", "Machado de Assis", "Literatura Brasileira", 1881, "A1-02", 2),
    ("Quincas Borba", "Machado de Assis", "Literatura Brasileira", 1891, "A1-03", 1),
    ("O Cortiço", "Aluísio Azevedo", "Literatura Brasileira", 1890, "A1-07", 3),
    ("Vidas Secas", "Graciliano Ramos", "Literatura Brasileira", 1938, "A1-08", 2),
    ("Capitães da Areia", "Jorge Amado", "Literatura Brasileira", 1937, "A1-09", 2),
    ("Grande Sertão: Veredas", "João Guimarães Rosa", "Literatura Brasileira", 1956, "A1-10", 1),
    ("A Hora da Estrela", "Clarice Lispector", "Literatura Brasileira", 1977, "A1-11", 2),
    ("Laços de Família", "Clarice Lispector", "Literatura Brasileira", 1960, "A1-12", 1),
    ("O Guarani", "José de Alencar", "Literatura Brasileira", 1857, "A1-13", 2),
    ("Iracema", "José de Alencar", "Literatura Brasileira", 1865, "A1-14", 3),
    ("Triste Fim de Policarpo Quaresma", "Lima Barreto", "Literatura Brasileira", 1915, "A1-15", 1),
    ("Macunaíma", "Mário de Andrade", "Literatura Brasileira", 1928, "A1-16", 2),
    # Literatura estrangeira
    ("1984", "George Orwell", "Literatura Estrangeira", 1949, "A2-01", 1),
    ("A Revolução dos Bichos", "George Orwell", "Literatura Estrangeira", 1945, "A2-02", 3),
    ("O Pequeno Príncipe", "Antoine de Saint-Exupéry", "Literatura Estrangeira", 1943, "A2-03", 4),
    ("Dom Quixote", "Miguel de Cervantes", "Literatura Estrangeira", 1605, "A2-04", 1),
    ("Cem Anos de Solidão", "Gabriel García Márquez", "Literatura Estrangeira", 1967, "A2-05", 2),
    ("Crime e Castigo", "Fiódor Dostoiévski", "Literatura Estrangeira", 1866, "A2-06", 2),
    ("Orgulho e Preconceito", "Jane Austen", "Literatura Estrangeira", 1813, "A2-07", 2),
    ("O Hobbit", "J. R. R. Tolkien", "Literatura Estrangeira", 1937, "A2-08", 3),
    ("Fahrenheit 451", "Ray Bradbury", "Literatura Estrangeira", 1953, "A2-09", 2),
    ("Admirável Mundo Novo", "Aldous Huxley", "Literatura Estrangeira", 1932, "A2-10", 1),
    # Tecnologia
    ("Engenharia de Software", "Ian Sommerville", "Tecnologia", 2011, "C3-02", 1),
    ("Código Limpo", "Robert C. Martin", "Tecnologia", 2009, "C3-03", 1),
    ("Arquitetura Limpa", "Robert C. Martin", "Tecnologia", 2019, "C3-04", 2),
    ("Padrões de Projeto", "Erich Gamma et al.", "Tecnologia", 2000, "C3-05", 2),
    ("Refatoração", "Martin Fowler", "Tecnologia", 2020, "C3-06", 2),
    ("Algoritmos: Teoria e Prática", "Thomas H. Cormen et al.", "Tecnologia", 2012, "C3-07", 3),
    ("Sistemas de Banco de Dados", "Ramez Elmasri e Shamkant Navathe", "Tecnologia", 2018, "C3-08", 2),
    ("Redes de Computadores", "Andrew S. Tanenbaum", "Tecnologia", 2011, "C3-09", 2),
    ("Sistemas Operacionais Modernos", "Andrew S. Tanenbaum", "Tecnologia", 2015, "C3-10", 2),
    ("Python Fluente", "Luciano Ramalho", "Tecnologia", 2023, "C3-11", 3),
    # Gestão
    ("Gerenciamento de Projetos", "PMI", "Gestão", 2021, "B2-05", 1),
    ("O Mítico Homem-Mês", "Frederick P. Brooks Jr.", "Gestão", 1995, "B2-06", 1),
    ("Scrum: a Arte de Fazer o Dobro do Trabalho na Metade do Tempo", "Jeff Sutherland", "Gestão", 2014, "B2-07", 2),
    ("Introdução à Teoria Geral da Administração", "Idalberto Chiavenato", "Gestão", 2014, "B2-08", 3),
    # Ciências e divulgação
    ("Uma Breve História do Tempo", "Stephen Hawking", "Ciências", 1988, "D4-01", 2),
    ("Cosmos", "Carl Sagan", "Ciências", 1980, "D4-02", 2),
    ("O Gene Egoísta", "Richard Dawkins", "Ciências", 1976, "D4-03", 1),
    ("Sapiens: Uma Breve História da Humanidade", "Yuval Noah Harari", "Ciências", 2011, "D4-04", 1),
]

EDITORAS = ["Editora Horizonte", "Editora Aurora", "Casa do Saber", "Editora Meridiano", "Livros do Norte"]


def com_isbn_e_editora():
    """Gera dicts prontos para services.criar_livro (ISBN fictício 978-00-xxxxxxxx para os não fixos)."""
    for i, (titulo, autores, categoria, ano, loc, qtd) in enumerate(LIVROS, start=1):
        yield {
            "titulo": titulo, "autores": autores, "categoria": categoria, "ano": str(ano),
            "localizacao": loc, "quantidade": str(qtd),
            "editora": EDITORAS[i % len(EDITORAS)],
            "isbn": FIXOS.get(titulo, f"97800{i:08d}"),
            "sinopse": f"Exemplar de demonstração (catálogo mock): {titulo}.",
        }


def carregar(somente_livros=False):
    """Retorna quantos livros novos foram criados."""
    if not somente_livros and not Usuario.query.filter_by(matricula_cpf="biblio").first():
        services.criar_usuario({"nome": "Mariana Oliveira", "matricula_cpf": "biblio", "email": "mariana@biblioteca.local",
                                "perfil": "Bibliotecário", "senha": "biblio123"})
        services.criar_usuario({"nome": "Aluno Exemplo", "matricula_cpf": "aluno", "email": "aluno@biblioteca.local",
                                "perfil": "Usuário Comum", "senha": "aluno123"})
        services.criar_usuario({"nome": "Aluna Dois", "matricula_cpf": "aluno2", "email": "aluno2@biblioteca.local",
                                "perfil": "Usuário Comum", "senha": "aluno123"})

    novos = 0
    for dados in com_isbn_e_editora():
        if not Livro.query.filter_by(isbn=dados["isbn"]).first():
            services.criar_livro(dados)
            novos += 1

    # Empréstimos de exemplo (só na primeira carga) para o catálogo mostrar livros indisponíveis
    if novos and not somente_livros and Emprestimo.query.count() == 0:
        aluno = Usuario.query.filter_by(matricula_cpf="aluno").first()
        aluna2 = Usuario.query.filter_by(matricula_cpf="aluno2").first()
        l1984 = Livro.query.filter_by(titulo="1984").first()
        limpo = Livro.query.filter_by(titulo="Código Limpo").first()
        services.registrar_emprestimo(aluno.id, l1984.id)  # indisponível (1 exemplar)
        services.registrar_emprestimo(aluna2.id, limpo.id, agora=datetime.now() - timedelta(days=20))  # em atraso
    return novos


if __name__ == "__main__":
    import sys
    from app import create_app

    with create_app().app_context():
        novos = carregar(somente_livros="--somente-livros" in sys.argv)
        print(f"Dados de demonstração prontos: {novos} livro(s) novo(s), total no acervo = {Livro.query.count()}.")
