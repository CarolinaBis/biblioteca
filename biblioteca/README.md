# Sistema de Gerenciamento de Biblioteca

Implementação simples dos 14 pacotes de trabalho da EAP (D8) e das atividades do cronograma (D9).
Stack: **Python + Flask + SQLAlchemy**, senhas com **bcrypt**, banco **PostgreSQL** (ou SQLite para testar rápido).

## Estrutura

```
biblioteca/
├── app.py              # aplicação Flask (fábrica `create_app` + ponto de entrada)
├── models.py           # tabelas do banco
├── services.py         # regras de negócio (empréstimo, multa, reserva, fila...)
├── views.py            # rotas/telas e controle de acesso
├── dados_demo.py       # catálogo mock + usuários de exemplo (python dados_demo.py)
├── migracao_legado.py  # migração do sistema antigo (JSON) + relatório
├── templates/          # páginas HTML (CSS embutido em base.html)
├── requirements.txt    # dependências (versões fixas)
└── README.md           # este arquivo: como rodar, manual e modelo de dados
```
(Além do `.gitignore`.)

## Como rodar (local)

Requer **Python 3.12 ou superior**.

```bash
python -m venv venv && source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
python app.py                                        # http://127.0.0.1:5000
```

- Sem configuração, usa **SQLite** (arquivo `instance/biblioteca.db`).
- Para **PostgreSQL**: `export DATABASE_URL=postgresql://usuario:senha@localhost:5432/biblioteca`
  (o banco deve existir; as tabelas são criadas automaticamente na primeira execução).
- Opcional: `python dados_demo.py` carrega o **catálogo mock** (41 livros em 5 categorias), usuários de exemplo e 2 empréstimos
  (um em atraso). É seguro rodar mais de uma vez. ISBNs, editoras, anos e localizações do mock são fictícios.

### Logins
| Perfil | Matrícula/CPF | Senha | Origem |
|---|---|---|---|
| Administrador | `admin` | `admin123` (ou variável `ADMIN_SENHA`) | criado no primeiro acesso |
| Bibliotecário | `biblio` | `biblio123` | `dados_demo.py` |
| Usuário Comum | `aluno` / `aluno2` | `aluno123` | `dados_demo.py` |

**Troque a senha do admin e defina `SECRET_KEY` fora do ambiente de teste.**

## Mapa EAP → código
| Pacote | Onde está |
|---|---|
| 1.1 Cadastro de Livros | `services.criar_livro` · tela `/livros/novo` (campos obrigatórios + ISBN único) |
| 1.2 Consulta do Acervo | `services.buscar_livros` · tela `/livros` (título, autor, ISBN, editora, categoria; índices no banco) |
| 1.3 Edição/Exclusão de Livros | `/livros/<id>/editar`, exclusão **lógica** (histórico de empréstimos preservado) |
| 2.1 Cadastro de Usuários | `services.criar_usuario` · `/usuarios/novo` (matrícula/CPF único, perfil) |
| 2.2 Autenticação e Acesso | `/login`, hash bcrypt, decorator `exige(...)` em `views.py`, `/recuperar-senha` |
| 2.3 Edição/Exclusão de Usuários | `/usuarios/<id>/editar`, exclusão lógica |
| 3.1 Empréstimos | `services.registrar_emprestimo` · `/emprestimos` (só livro disponível; prazo calculado) |
| 3.2 Devoluções | `services.registrar_devolucao` (livro volta a ficar disponível) |
| 3.3 Multas | `services.calcular_multa` · valor/dia configurável em `/configuracoes` |
| 4.1 Reservas | `services.reservar` (disponível → reservado por 48h; indisponível → fila) |
| 4.2 Fila de Espera | `services.processar_filas` (ordem de solicitação + notificação ao devolver/expirar) |
| 5.1 Busca Pública (OPAC) | `/opac` (sem login): mostra o **acervo completo** paginado (20 por página), com atalhos por categoria e busca opcional |
| 5.2 Disponibilidade | `services.mapa_disponibilidade` (total − emprestados − reservas ativas) |
| 6.1 Migração do Legado | `python migracao_legado.py arquivo.json` (gera relatório .txt). Para testar: `python migracao_legado.py --gerar-exemplo` |

## Perfis
- **Administrador:** tudo (usuários, configurações, livros, empréstimos).
- **Bibliotecário:** livros, empréstimos e devoluções.
- **Usuário Comum:** consulta, reserva livros, vê seus empréstimos, reservas, multas e notificações.

## Manual do usuário

### Para qualquer pessoa (sem login)
1. Abra o **Catálogo** (página inicial): ele já lista todo o acervo, 20 livros por página. Use os botões de categoria para filtrar.
2. Para procurar algo específico, preencha um ou mais campos (título, autor, ISBN, editora, categoria) e clique em **Buscar**.
3. A tabela mostra a localização do livro e quantos exemplares estão disponíveis.

### Usuário Comum
1. Clique em **Entrar** e informe sua matrícula/CPF e senha. Esqueceu a senha? Use **Esqueci minha senha**.
2. No Catálogo, clique em **Reservar** (livro disponível: você tem **48 horas** para retirar) ou **Entrar na fila** (livro indisponível: você será avisado quando chegar sua vez).
3. Em **Minha conta** você vê notificações, empréstimos, reservas (pode cancelar) e multas.

### Bibliotecário
- **Livros:** cadastrar, buscar, editar e excluir exemplares do acervo. Livros emprestados não podem ser excluídos.
- **Empréstimos:** informe a matrícula/CPF do usuário e o ISBN do livro e clique em *Registrar empréstimo*. A data de devolução é calculada automaticamente.
- **Devolução:** na lista de empréstimos em aberto, clique em *Registrar devolução*. Se houve atraso, o sistema calcula e registra a multa e avisa o próximo da fila.

### Administrador
Tudo o que o Bibliotecário faz, mais:
- **Usuários:** cadastrar, editar e excluir (perfil Administrador, Bibliotecário ou Usuário Comum).
- **Configurações:** valor da multa por dia, prazo de empréstimo e limite de livros por usuário.


## Modelo de dados (MER)

```mermaid
erDiagram
    USUARIOS ||--o{ EMPRESTIMOS : realiza
    LIVROS   ||--o{ EMPRESTIMOS : "é emprestado em"
    EMPRESTIMOS ||--o| MULTAS : "pode gerar"
    USUARIOS ||--o{ MULTAS : recebe
    USUARIOS ||--o{ RESERVAS : faz
    LIVROS   ||--o{ RESERVAS : "é reservado em"
    USUARIOS ||--o{ NOTIFICACOES : recebe

    USUARIOS { int id PK
        string nome
        string matricula_cpf UK
        string email
        string telefone
        string endereco
        string perfil "Administrador | Bibliotecário | Usuário Comum"
        string senha_hash "bcrypt"
        date data_cadastro
        bool ativo "exclusão lógica" }
    LIVROS { int id PK
        string titulo
        string autores
        string editora
        string edicao
        string isbn UK
        int ano
        string categoria
        string localizacao
        int quantidade "total de exemplares"
        text sinopse
        bool ativo "exclusão lógica" }
    EMPRESTIMOS { int id PK
        int usuario_id FK
        int livro_id FK
        date data_retirada
        date data_prevista
        date data_devolucao "nulo = em aberto" }
    MULTAS { int id PK
        int usuario_id FK
        int emprestimo_id FK
        int dias_atraso
        decimal valor
        date data }
    RESERVAS { int id PK
        int usuario_id FK
        int livro_id FK
        datetime criada_em
        string status "Em espera | Disponível | Retirada | Expirada | Cancelada"
        datetime expira_em "48h após ficar Disponível" }
    NOTIFICACOES { int id PK
        int usuario_id FK
        string mensagem
        datetime criada_em
        bool lida }
    CONFIGURACOES { string chave PK
        string valor "multa_por_dia, prazo_emprestimo_dias, max_livros" }
```

Disponibilidade de um livro = `quantidade` − empréstimos em aberto − reservas com status *Disponível* ainda dentro das 48h.


## Premissas 
1. **Prazo de empréstimo = 14 dias; máximo = 3 livros por usuário; multa = R$ 1,00/dia.** Tudo editável em `/configuracoes`.
   Pelo TAP, quem define essas regras é a especialista de negócio (Mariana Oliveira): confirme os valores com ela.
2. **Formato do legado:** o TAP diz "CSV/JSON" e o cronograma (D9) fala em JSON; foi implementado só **JSON**. O layout dos campos não foi informado. Foi assumido `{"livros": [...], "usuarios": [...]}` com nomes de campos comuns
   (ajuste `ALIAS` em `migracao_legado.py`). Usuários migrados recebem senha aleatória e usam "Esqueci minha senha".
3. **Notificações** ficam dentro do sistema (aba "Minha conta"); **não há envio de e-mail/SMS**.
   O link de recuperação de senha é impresso no **console do servidor**.
4. Quem pode cadastrar/editar usuários: só o Administrador.
5. Não há cobrança/quitação de multas (o pacote 3.3 pede apenas cálculo e registro no histórico).
6. Funcionalidades de apoio do cronograma (UAT, implantação, documentação — AT34 a AT36) não geram código; este README cobre a parte técnica.


