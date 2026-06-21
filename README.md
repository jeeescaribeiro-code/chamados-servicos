# chamados&serviços

Aplicação web de portfólio para abertura, acompanhamento e gerenciamento de chamados técnicos e solicitações de serviços, integrada a um banco MySQL e preparada para análise em Power BI.

O projeto simula um fluxo corporativo completo:

```text
App Web -> API Python -> MySQL -> Power BI
```

## Tecnologias

- Python
- API local
- MySQL
- SQL
- HTML
- CSS
- JavaScript
- Power BI
- DAX

## Funcionalidades

- Cadastro e login de usuários.
- Abertura de chamados técnicos.
- Lista de chamados com status, prioridade, SLA e responsável.
- Detalhes do chamado com chat e timeline.
- Dashboard do usuário.
- Dashboard do administrador/atendente.
- Tela de serviços disponíveis.
- Base de conhecimento.
- Relatórios e indicadores.
- Sugestão automática de categoria, prioridade e SLA com base no texto do chamado.

## Integração com MySQL

A aplicação usa o banco `helpdesk_sla`.

Principais integrações:

- Cadastro e login ficam em `app_usuarios`.
- O cadastro também cria registro em `usuarios`.
- Chamados novos são gravados em `chamados`.
- Título e descrição ficam em `chamado_detalhes`.
- Comentários do chat ficam em `chamado_comentarios`.
- Eventos da timeline ficam em `chamado_historico`.
- Categorias, SLA, atendentes e departamentos vêm das tabelas existentes:
  - `categorias`
  - `sla_regras`
  - `atendentes`
  - `departamentos`
  - `usuarios`

## Indicadores Trabalhados

- Total de chamados.
- Chamados abertos.
- Chamados dentro e fora do SLA.
- Fila crítica por prioridade e vencimento.
- Custo por categoria.
- Categoria que mais gera gasto.
- Departamento que mais abre chamados.
- Departamento que mais gera custo.
- Perfil de usuário que mais solicita suporte.
- Atendentes com maiores notas.
- Satisfação média.

## Antes de Rodar

Confira o arquivo `config.json`.

Se ele não existir, crie um arquivo com base neste exemplo:

```json
{
  "host": "localhost",
  "port": 3306,
  "user": "root",
  "password": "SUA_SENHA_AQUI",
  "database": "helpdesk_sla",
  "mysql_path": "C:\\Program Files\\MySQL\\MySQL Server 8.0\\bin\\mysql.exe"
}
```

Nunca publique o `config.json` com senha real no GitHub.

## Como Rodar Localmente

Clique duas vezes em:

```text
run_app.bat
```

Depois acesse no navegador:

```text
http://127.0.0.1:8060
```

## Login Demo

O app cria um login demonstrativo se houver usuários no banco:

```text
ana.silva@empresa.com
123456
```

Também é possível criar uma conta pela tela de login.

## Power BI

O Power BI deve conectar diretamente ao banco MySQL `helpdesk_sla`.

Depois de abrir chamados pelo app:

- Se o Power BI estiver em modo Importar, clique em `Atualizar`.
- Se estiver em DirectQuery, os dados são consultados diretamente do MySQL.

## Observação Para GitHub Pages

O GitHub Pages exibe apenas a interface estática do `index.html`.

A versão completa, com API Python e MySQL, precisa ser executada localmente.
