from __future__ import annotations

import hashlib
import importlib
import json
import os
import re
import secrets
import subprocess
from datetime import datetime, timedelta
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

try:
    mysql_connector = importlib.import_module("mysql.connector")
except ModuleNotFoundError:
    mysql_connector = None


APP_DIR = Path(__file__).resolve().parent
HOST = os.getenv("HELPDESK_APP_HOST", "127.0.0.1")
PORT = int(os.getenv("HELPDESK_APP_PORT", "8060"))
SESSIONS: dict[str, dict] = {}

DEFAULT_CONFIG = {
    "host": os.getenv("HELPDESK_DB_HOST", "localhost"),
    "port": int(os.getenv("HELPDESK_DB_PORT", "3306")),
    "user": os.getenv("HELPDESK_DB_USER", "root"),
    "password": os.getenv("HELPDESK_DB_PASSWORD", ""),
    "database": os.getenv("HELPDESK_DB_NAME", "helpdesk_sla"),
    "mysql_path": os.getenv("HELPDESK_MYSQL_PATH", r"C:\Program Files\MySQL\MySQL Server 8.0\bin\mysql.exe"),
}


def load_config() -> dict:
    config = DEFAULT_CONFIG.copy()
    config_path = APP_DIR / "config.json"
    if config_path.exists():
        config.update(json.loads(config_path.read_text(encoding="utf-8")))
    return config


def json_default(value):
    if isinstance(value, (datetime,)):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, Decimal):
        return float(value)
    return str(value)


def content_type_for(path: Path) -> str:
    return {
        ".html": "text/html; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".js": "application/javascript; charset=utf-8",
        ".png": "image/png",
        ".svg": "image/svg+xml; charset=utf-8",
    }.get(path.suffix.lower(), "application/octet-stream")


def db_connect():
    if mysql_connector is None:
        raise RuntimeError("mysql-connector-python ausente")
    config = load_config().copy()
    config.pop("mysql_path", None)
    return mysql_connector.connect(**config)


def sql_literal(value) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float, Decimal)):
        return str(value)
    if isinstance(value, datetime):
        value = value.strftime("%Y-%m-%d %H:%M:%S")
    text = str(value).replace("\\", "\\\\").replace("'", "''")
    return f"'{text}'"


def interpolate(sql: str, params: tuple = ()) -> str:
    for param in params:
        sql = sql.replace("%s", sql_literal(param), 1)
    return sql


def mysql_cli_command(sql: str) -> list[str]:
    config = load_config()
    command = [
        config.get("mysql_path") or "mysql",
        "-h",
        str(config["host"]),
        "-P",
        str(config["port"]),
        "-u",
        str(config["user"]),
        "--default-character-set=utf8mb4",
        "--batch",
        "--raw",
        "--database",
        str(config["database"]),
        "--execute",
        sql,
    ]
    if config.get("password"):
        command.insert(7, f"-p{config['password']}")
    return command


def run_mysql_cli(sql: str) -> str:
    result = subprocess.run(
        mysql_cli_command(sql),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "Erro ao executar mysql.exe")
    return result.stdout


def parse_tsv(output: str) -> list[dict]:
    lines = [line for line in output.splitlines() if line.strip()]
    if not lines:
        return []
    headers = lines[0].split("\t")
    rows = []
    for line in lines[1:]:
        values = line.split("\t")
        rows.append({
            header: None if idx >= len(values) or values[idx] in {"NULL", "\\N"} else values[idx]
            for idx, header in enumerate(headers)
        })
    return rows


def query_all(sql: str, params: tuple = ()) -> list[dict]:
    if mysql_connector is None:
        return parse_tsv(run_mysql_cli(interpolate(sql, params)))
    with db_connect() as conn:
        cur = conn.cursor(dictionary=True)
        cur.execute(sql, params)
        rows = cur.fetchall()
        cur.close()
        return rows


def execute(sql: str, params: tuple = ()) -> int:
    if mysql_connector is None:
        run_mysql_cli(interpolate(sql, params))
        return 0
    with db_connect() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        conn.commit()
        count = cur.rowcount
        cur.close()
        return count


def ensure_app_tables() -> None:
    execute(
        """
        CREATE TABLE IF NOT EXISTS app_usuarios (
          email VARCHAR(120) PRIMARY KEY,
          senha_hash VARCHAR(128) NOT NULL,
          usuario_id VARCHAR(10) NOT NULL,
          papel VARCHAR(20) NOT NULL DEFAULT 'usuario',
          criado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY (usuario_id) REFERENCES usuarios(usuario_id)
        )
        """
    )
    execute(
        """
        CREATE TABLE IF NOT EXISTS chamado_detalhes (
          ticket_id VARCHAR(20) PRIMARY KEY,
          titulo VARCHAR(180),
          descricao TEXT,
          criado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY (ticket_id) REFERENCES chamados(ticket_id)
        )
        """
    )
    execute(
        """
        CREATE TABLE IF NOT EXISTS chamado_comentarios (
          comentario_id INT AUTO_INCREMENT PRIMARY KEY,
          ticket_id VARCHAR(20) NOT NULL,
          autor VARCHAR(120) NOT NULL,
          mensagem TEXT NOT NULL,
          criado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY (ticket_id) REFERENCES chamados(ticket_id)
        )
        """
    )
    execute(
        """
        CREATE TABLE IF NOT EXISTS chamado_historico (
          historico_id INT AUTO_INCREMENT PRIMARY KEY,
          ticket_id VARCHAR(20) NOT NULL,
          evento VARCHAR(160) NOT NULL,
          criado_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY (ticket_id) REFERENCES chamados(ticket_id)
        )
        """
    )


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def next_id(table: str, column: str, prefix: str, width: int) -> str:
    rows = query_all(f"SELECT MAX({column}) AS ultimo FROM {table}")
    ultimo = rows[0]["ultimo"] if rows else None
    if not ultimo:
        return f"{prefix}{1:0{width}d}"
    match = re.search(r"(\d+)$", str(ultimo))
    number = int(match.group(1)) + 1 if match else 1
    return f"{prefix}{number:0{width}d}"


def next_ticket_id() -> str:
    return next_id("chamados", "ticket_id", "TCK-", 5)


def get_user_from_token(headers) -> dict | None:
    auth = headers.get("Authorization", "")
    token = auth.replace("Bearer ", "").strip()
    return SESSIONS.get(token)


def session_for(email: str) -> dict:
    ensure_app_tables()
    rows = query_all(
        """
        SELECT au.email, au.usuario_id, au.papel, u.nome_usuario, u.departamento_id,
               u.nome_departamento, u.unidade, u.perfil
        FROM app_usuarios au
        JOIN usuarios u ON u.usuario_id = au.usuario_id
        WHERE au.email = %s
        """,
        (email,),
    )
    if not rows:
        raise ValueError("Usuário de aplicação não encontrado.")
    token = secrets.token_urlsafe(32)
    SESSIONS[token] = rows[0]
    return {"token": token, "user": rows[0]}


def register(payload: dict) -> dict:
    ensure_app_tables()
    nome = payload.get("nome", "").strip()
    email = payload.get("email", "").strip().lower()
    senha = payload.get("senha", "").strip()
    departamento_id = payload.get("departamento_id", "").strip()
    unidade = payload.get("unidade", "Remoto").strip() or "Remoto"
    perfil = payload.get("perfil", "Analista").strip() or "Analista"
    papel = payload.get("papel", "usuario").strip() or "usuario"
    if not nome or not email or not senha or not departamento_id:
        raise ValueError("Preencha nome, e-mail, senha e departamento.")
    if query_all("SELECT email FROM app_usuarios WHERE email = %s", (email,)):
        raise ValueError("E-mail já cadastrado.")
    dep = query_all("SELECT nome_departamento FROM departamentos WHERE departamento_id = %s", (departamento_id,))
    if not dep:
        raise ValueError("Departamento inválido.")
    usuario_id = next_id("usuarios", "usuario_id", "USR", 3)
    execute(
        """
        INSERT INTO usuarios (usuario_id, nome_usuario, departamento_id, nome_departamento, unidade, perfil)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (usuario_id, nome, departamento_id, dep[0]["nome_departamento"], unidade, perfil),
    )
    execute(
        """
        INSERT INTO app_usuarios (email, senha_hash, usuario_id, papel)
        VALUES (%s, %s, %s, %s)
        """,
        (email, sha(senha), usuario_id, papel),
    )
    return session_for(email)


def login(payload: dict) -> dict:
    ensure_app_tables()
    email = payload.get("email", "").strip().lower()
    senha = payload.get("senha", "").strip()
    rows = query_all("SELECT senha_hash FROM app_usuarios WHERE email = %s", (email,))
    if not rows or rows[0]["senha_hash"] != sha(senha):
        raise ValueError("E-mail ou senha inválidos.")
    return session_for(email)


def bootstrap_demo_user() -> None:
    ensure_app_tables()
    if query_all("SELECT email FROM app_usuarios WHERE email = 'ana.silva@empresa.com'"):
        return
    user = query_all("SELECT usuario_id FROM usuarios ORDER BY usuario_id LIMIT 1")
    if not user:
        return
    execute(
        """
        INSERT INTO app_usuarios (email, senha_hash, usuario_id, papel)
        VALUES ('ana.silva@empresa.com', %s, %s, 'admin')
        """,
        (sha("123456"), user[0]["usuario_id"]),
    )


def options() -> dict:
    return {
        "departamentos": query_all("SELECT departamento_id, nome_departamento, area FROM departamentos ORDER BY nome_departamento"),
        "usuarios": query_all("SELECT usuario_id, nome_usuario, departamento_id, nome_departamento, unidade, perfil FROM usuarios ORDER BY nome_usuario"),
        "categorias": query_all("SELECT categoria_id, nome_categoria, especialista_padrao, subcategorias FROM categorias ORDER BY nome_categoria"),
        "atendentes": query_all("SELECT atendente_id, nome_atendente, equipe, nivel FROM atendentes ORDER BY nome_atendente"),
        "sla_regras": query_all("SELECT categoria_id, prioridade, sla_resolucao_horas, sla_primeira_resposta_horas FROM sla_regras"),
        "prioridades": ["Baixa", "Media", "Alta", "Critica"],
        "status": ["Em atendimento", "Aguardando usuario", "Resolvido", "Fechado", "Cancelado"],
        "canais": ["Portal", "E-mail", "Teams", "Telefone", "Monitoramento"],
    }


def parse_dt(value: str | None) -> datetime:
    if not value:
        return datetime.now().replace(second=0, microsecond=0)
    return datetime.strptime(value, "%Y-%m-%dT%H:%M")


def create_ticket(payload: dict, user: dict | None) -> dict:
    ensure_app_tables()
    usuario_id = payload.get("usuario_id") or (user or {}).get("usuario_id")
    categoria_id = payload.get("categoria_id")
    prioridade = payload.get("prioridade")
    titulo = payload.get("titulo", "").strip() or "Solicitação sem título"
    descricao = payload.get("descricao", "").strip()
    canal = payload.get("canal", "Portal")
    subcategoria = payload.get("subcategoria") or "Nao informado"
    abertura = parse_dt(payload.get("data_abertura"))
    if not usuario_id or not categoria_id or not prioridade:
        raise ValueError("Usuário, categoria e prioridade são obrigatórios.")
    usuario = query_all("SELECT * FROM usuarios WHERE usuario_id = %s", (usuario_id,))
    categoria = query_all("SELECT * FROM categorias WHERE categoria_id = %s", (categoria_id,))
    sla = query_all(
        "SELECT * FROM sla_regras WHERE categoria_id = %s AND prioridade = %s",
        (categoria_id, prioridade),
    )
    if not usuario or not categoria or not sla:
        raise ValueError("Dados inválidos para abertura do chamado.")
    usuario, categoria, sla = usuario[0], categoria[0], sla[0]
    atendente_id = payload.get("atendente_id") or categoria["especialista_padrao"]
    sla_horas = float(sla["sla_resolucao_horas"])
    primeira_horas = float(sla["sla_primeira_resposta_horas"])
    vencimento = abertura + timedelta(hours=sla_horas)
    primeira_resposta = abertura + timedelta(hours=primeira_horas)
    ticket_id = next_ticket_id()
    nivel = query_all("SELECT nivel FROM atendentes WHERE atendente_id = %s", (atendente_id,))
    nivel = nivel[0]["nivel"] if nivel else "N1"
    custo_hora = {"N1": 45, "N2": 72, "N3": 110}.get(nivel, 60)
    custo_estimado = round(max(1, sla_horas * 0.35) * custo_hora, 2)
    execute(
        """
        INSERT INTO chamados (
          ticket_id, data_abertura, data_vencimento_sla, data_primeira_resposta,
          data_fechamento, usuario_id, departamento_id, unidade, categoria_id,
          nome_categoria, subcategoria, prioridade, status, canal, atendente_id,
          horas_primeira_resposta, horas_resolucao, sla_resolucao_horas,
          dentro_sla, atraso_horas, reaberto, escalado, satisfacao_cliente, custo_estimado
        )
        VALUES (
          %s, %s, %s, %s,
          NULL, %s, %s, %s, %s,
          %s, %s, %s, 'Em atendimento', %s, %s,
          %s, NULL, %s,
          '', NULL, 'Nao', %s, NULL, %s
        )
        """,
        (
            ticket_id, abertura, vencimento, primeira_resposta, usuario_id,
            usuario["departamento_id"], usuario["unidade"], categoria_id,
            categoria["nome_categoria"], subcategoria, prioridade, canal,
            atendente_id, primeira_horas, sla_horas,
            "Sim" if prioridade in {"Alta", "Critica"} else "Nao",
            custo_estimado,
        ),
    )
    execute(
        "INSERT INTO chamado_detalhes (ticket_id, titulo, descricao) VALUES (%s, %s, %s)",
        (ticket_id, titulo, descricao),
    )
    execute("INSERT INTO chamado_historico (ticket_id, evento) VALUES (%s, %s)", (ticket_id, "Chamado aberto"))
    return get_ticket(ticket_id)


def sla_label(row: dict) -> str:
    if row.get("status") in {"Resolvido", "Fechado", "Cancelado"}:
        return "Concluído"
    venc = row.get("data_vencimento_sla")
    if isinstance(venc, str):
        try:
            venc = datetime.strptime(venc, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return str(venc)
    diff = venc - datetime.now() if isinstance(venc, datetime) else timedelta()
    hours = round(diff.total_seconds() / 3600, 1)
    if hours < 0:
        return f"{abs(hours)}h vencido"
    if hours < 1:
        return "menos de 1h"
    return f"{hours}h restantes"


def ticket_rows(where: str = "", params: tuple = (), limit: int = 200) -> list[dict]:
    safe_limit = max(1, min(int(limit), 500))
    rows = query_all(
        f"""
        SELECT c.ticket_id, COALESCE(cd.titulo, c.subcategoria) AS titulo, cd.descricao,
               c.nome_categoria, c.prioridade, c.status, c.data_abertura,
               c.data_vencimento_sla, c.usuario_id, u.nome_usuario AS solicitante,
               c.atendente_id, a.nome_atendente AS responsavel,
               d.nome_departamento, c.custo_estimado, c.dentro_sla
        FROM chamados c
        LEFT JOIN chamado_detalhes cd ON cd.ticket_id = c.ticket_id
        LEFT JOIN usuarios u ON u.usuario_id = c.usuario_id
        LEFT JOIN atendentes a ON a.atendente_id = c.atendente_id
        LEFT JOIN departamentos d ON d.departamento_id = c.departamento_id
        {where}
        ORDER BY c.ticket_id DESC
        LIMIT {safe_limit}
        """,
        params,
    )
    for row in rows:
        row["sla_label"] = sla_label(row)
        row["risk"] = row["status"] in {"Em atendimento", "Aguardando usuario"} and ("vencido" in row["sla_label"] or "menos" in row["sla_label"])
    return rows


def list_tickets(query: dict, user: dict | None) -> list[dict]:
    params = []
    filters = []
    if query.get("mine", ["0"])[0] == "1" and user:
        filters.append("c.usuario_id = %s")
        params.append(user["usuario_id"])
    status = query.get("status", [""])[0]
    priority = query.get("prioridade", [""])[0]
    if status and status != "Todos":
        filters.append("c.status = %s")
        params.append(status)
    if priority and priority != "Todas prioridades":
        filters.append("c.prioridade = %s")
        params.append(priority)
    where = "WHERE " + " AND ".join(filters) if filters else ""
    return ticket_rows(where, tuple(params), int(query.get("limit", ["200"])[0]))


def get_ticket(ticket_id: str) -> dict:
    rows = ticket_rows("WHERE c.ticket_id = %s", (ticket_id,), 1)
    if not rows:
        raise ValueError("Chamado não encontrado.")
    ticket = rows[0]
    ticket["comentarios"] = query_all(
        "SELECT autor, mensagem, criado_em FROM chamado_comentarios WHERE ticket_id = %s ORDER BY comentario_id",
        (ticket_id,),
    )
    ticket["historico"] = query_all(
        "SELECT evento, criado_em FROM chamado_historico WHERE ticket_id = %s ORDER BY historico_id",
        (ticket_id,),
    )
    return ticket


def add_comment(payload: dict, user: dict | None) -> dict:
    ticket_id = payload.get("ticket_id")
    mensagem = payload.get("mensagem", "").strip()
    if not ticket_id or not mensagem:
        raise ValueError("Ticket e mensagem são obrigatórios.")
    autor = (user or {}).get("nome_usuario") or payload.get("autor") or "Usuário"
    execute(
        "INSERT INTO chamado_comentarios (ticket_id, autor, mensagem) VALUES (%s, %s, %s)",
        (ticket_id, autor, mensagem),
    )
    execute("INSERT INTO chamado_historico (ticket_id, evento) VALUES (%s, %s)", (ticket_id, f"Comentário adicionado por {autor}"))
    return get_ticket(ticket_id)


def update_ticket(payload: dict) -> dict:
    ticket_id = payload.get("ticket_id")
    fields = []
    params = []
    for key in ["status", "prioridade", "atendente_id"]:
        if payload.get(key):
            column = "prioridade" if key == "prioridade" else key
            fields.append(f"{column} = %s")
            params.append(payload[key])
    if not ticket_id or not fields:
        raise ValueError("Informe ticket e campos para atualizar.")
    params.append(ticket_id)
    execute(f"UPDATE chamados SET {', '.join(fields)} WHERE ticket_id = %s", tuple(params))
    execute("INSERT INTO chamado_historico (ticket_id, evento) VALUES (%s, %s)", (ticket_id, "Chamado atualizado"))
    return get_ticket(ticket_id)


def metrics() -> dict:
    rows = query_all(
        """
        SELECT
          COUNT(*) AS total,
          SUM(CASE WHEN status IN ('Em atendimento','Aguardando usuario') THEN 1 ELSE 0 END) AS abertos,
          SUM(CASE WHEN status IN ('Em atendimento','Aguardando usuario') AND data_vencimento_sla < NOW() THEN 1 ELSE 0 END) AS sla_vencidos_abertos,
          SUM(CASE WHEN status IN ('Em atendimento','Aguardando usuario') AND data_vencimento_sla BETWEEN NOW() AND DATE_ADD(NOW(), INTERVAL 4 HOUR) THEN 1 ELSE 0 END) AS sla_risco,
          SUM(CASE WHEN dentro_sla = 'Sim' THEN 1 ELSE 0 END) AS dentro_sla,
          SUM(CASE WHEN status IN ('Resolvido','Fechado') THEN 1 ELSE 0 END) AS resolvidos,
          ROUND(AVG(satisfacao_cliente), 2) AS satisfacao,
          ROUND(SUM(custo_estimado), 2) AS custo_total,
          ROUND(AVG(horas_resolucao), 2) AS tempo_medio_resolucao,
          DATE_FORMAT(
            MAX(GREATEST(data_abertura, COALESCE(data_primeira_resposta, data_abertura), COALESCE(data_fechamento, data_abertura))),
            '%Y-%m-%d %H:%i:%s'
          ) AS ultima_atualizacao
        FROM chamados
        """
    )[0]
    for key in ["total", "abertos", "sla_vencidos_abertos", "sla_risco", "dentro_sla", "resolvidos"]:
        rows[key] = int(rows.get(key) or 0)
    return rows


class Handler(BaseHTTPRequestHandler):
    def send_json(self, data, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False, default=json_default).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path: Path, content_type: str) -> None:
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_payload(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8") or "{}")

    def current_user(self) -> dict | None:
        return get_user_from_token(self.headers)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        try:
            if parsed.path in {"/", "/index.html"}:
                return self.send_file(APP_DIR / "index.html", "text/html; charset=utf-8")
            if parsed.path == "/styles.css":
                return self.send_file(APP_DIR / "styles.css", "text/css; charset=utf-8")
            if parsed.path == "/script.js":
                return self.send_file(APP_DIR / "script.js", "application/javascript; charset=utf-8")
            if parsed.path.startswith("/assets/"):
                file = APP_DIR / parsed.path.lstrip("/")
                return self.send_file(file, content_type_for(file))
            if parsed.path == "/api/health":
                query_all("SELECT 1 AS ok")
                bootstrap_demo_user()
                return self.send_json({"ok": True, "database": load_config()["database"]})
            if parsed.path == "/api/options":
                return self.send_json(options())
            if parsed.path == "/api/me":
                return self.send_json({"user": self.current_user()})
            if parsed.path == "/api/metrics":
                return self.send_json(metrics())
            if parsed.path == "/api/tickets":
                return self.send_json({"tickets": list_tickets(qs, self.current_user())})
            if parsed.path == "/api/ticket":
                return self.send_json({"ticket": get_ticket(qs.get("id", [""])[0])})
            self.send_error(404)
        except Exception as exc:
            self.send_json({"ok": False, "error": str(exc)}, 500)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        payload = self.read_payload()
        try:
            if parsed.path == "/api/register":
                return self.send_json(register(payload))
            if parsed.path == "/api/login":
                return self.send_json(login(payload))
            if parsed.path == "/api/tickets":
                user = self.current_user()
                if not user:
                    return self.send_json({"ok": False, "error": "Faça login para abrir um chamado."}, 401)
                return self.send_json({"ticket": create_ticket(payload, user)})
            if parsed.path == "/api/comments":
                user = self.current_user()
                if not user:
                    return self.send_json({"ok": False, "error": "Faça login para comentar no chamado."}, 401)
                return self.send_json({"ticket": add_comment(payload, user)})
            if parsed.path == "/api/tickets/update":
                return self.send_json({"ticket": update_ticket(payload)})
            self.send_error(404)
        except ValueError as exc:
            self.send_json({"ok": False, "error": str(exc)}, 400)
        except Exception as exc:
            self.send_json({"ok": False, "error": str(exc)}, 500)

    def log_message(self, fmt: str, *args) -> None:
        print(f"[chamados&serviços] {fmt % args}")


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"chamados&serviços em http://{HOST}:{PORT}")
    print("Use o login demo: ana.silva@empresa.com / 123456")
    server.serve_forever()


if __name__ == "__main__":
    main()
