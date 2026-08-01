import os
import sys
import requests
import time
import re
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from PIL import Image
from io import BytesIO
import pytesseract
from bs4 import BeautifulSoup

# Força o Python a mostrar os prints imediatamente no Railway
sys.stdout.reconfigure(line_buffering=True)

# --- CONFIGURAÇÕES (VARIÁVEIS DO RAILWAY) ---
LOGIN_ID = os.getenv("LOGIN_ID")
SENHA = os.getenv("SENHA")
TG_TOKEN = os.getenv("TG_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")

if not all([LOGIN_ID, SENHA, TG_TOKEN, TG_CHAT_ID]):
    print("❌ ERRO: Variáveis de ambiente faltando. Configure no Railway.")
    sys.exit(1)

BASE = "http://www.proeisbm.cbmerj.rj.gov.br"
LOGIN_URL = f"{BASE}/index.php?option=com_inscricao&Itemid=82"

status_info = {"resultado": "Iniciando..."}

# --- SERVIDOR DE SAÚDE (Mantém o container vivo) ---
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(f"<h1>Bot Ativo</h1><p>{status_info['resultado']}</p>".encode())
    def log_message(self, *args): pass

def start_health_server():
    port = int(os.environ.get('PORT', 8080))
    server = HTTPServer(('0.0.0.0', port), HealthHandler)
    print(f"🖥️ Servidor de saúde rodando na porta {port}")
    server.serve_forever()

# --- SESSÃO HTTP ---
SESSAO = requests.Session()
SESSAO.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
})

# --- FUNÇÕES CORE ---

def resolver_captcha():
    """Baixa e resolve o captcha via OCR"""
    try:
        # Adiciona timestamp para evitar cache
        url_captcha = f"{BASE}/captcha2.php?t={int(time.time())}"
        resp = SESSAO.get(url_captcha, stream=True, timeout=10)
        
        if resp.status_code != 200:
            print("❌ Erro ao baixar imagem do captcha")
            return ""

        img = Image.open(BytesIO(resp.content))
        # Configuração focada em caracteres alfanuméricos curtos
        texto = pytesseract.image_to_string(
            img, 
            config='--psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
        ).strip().upper()
        
        # Limpa espaços e pega apenas os 4 primeiros caracteres
        clean_text = re.sub(r'[^A-Z0-9]', '', texto)[:4]
        print(f"🔐 Captcha detectado: '{clean_text}'")
        return clean_text if len(clean_text) == 4 else ""
    except Exception as e:
        print(f"💥 Erro no OCR: {e}")
        return ""

def get_csrf_token(soup):
    """Encontra o token de segurança do Joomla"""
    for inp in soup.find_all('input', {'type': 'hidden'}):
        name = inp.get('name', '')
        value = inp.get('value', '')
        # Tokens Joomla geralmente são hashes de 32 chars com valor '1'
        if value == '1' and len(name) == 32:
            try:
                int(name, 16) # Verifica se é hexadecimal
                return name, value
            except ValueError:
                continue
    return None, None

def avisar_telegram(msg):
    """Envia mensagem para o Telegram"""
    try:
        url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
        payload = {
            "chat_id": TG_CHAT_ID, 
            "text": msg, 
            "parse_mode": "HTML"
        }
        r = requests.post(url, data=payload, timeout=10)
        if r.status_code == 200:
            print("📩 Notificação enviada ao Telegram")
        else:
            print(f"⚠️ Falha ao enviar Telegram: {r.text}")
    except Exception as e:
        print(f"💥 Erro Telegram: {e}")

def fazer_login():
    """Realiza o login completo"""
    hora = time.strftime("%H:%M:%S")
    print(f"🔄 [{hora}] Iniciando processo de login...")
    
    try:
        # 1. Pegar página inicial para obter Cookie e Token
        resp_home = SESSAO.get(LOGIN_URL, timeout=15)
        soup = BeautifulSoup(resp_home.text, 'html.parser')
        
        token_name, token_val = get_csrf_token(soup)
        if not token_name:
            print("❌ Token CSRF não encontrado na página de login")
            return False

        # 2. Resolver Captcha
        captcha_sol = resolver_captcha()
        if not captcha_sol:
            print("❌ Falha ao resolver captcha")
            return False

        # 3. Enviar formulário de login
        dados_login = {
            "username": LOGIN_ID,
            "passwd": SENHA,
            "cd": captcha_sol,
            "option": "com_user",
            "task": "login",
            "return": "L2luZGV4LnBocD9vcHRpb249Y29tX2xvZ2luJkl0ZW1pZD05Mw==",
            token_name: token_val
        }
        
        resp_post = SESSAO.post(LOGIN_URL, data=dados_login, timeout=15)
        
        # 4. Verificar sucesso
        # Se tiver "logout" ou "sair" no HTML, estamos logados
        if "logout" in resp_post.text.lower() or "sair" in resp_post.text.lower():
            print(f"✅ [{hora}] Login realizado com sucesso!")
            status_info["resultado"] = "✅ Logado"
            return True
        else:
            # Tenta achar mensagem de erro específica
            soup_err = BeautifulSoup(resp_post.text, 'html.parser')
            erro_msg = soup_err.find(class_="error")
            txt_erro = erro_msg.get_text(strip=True) if erro_msg else "Credenciais inválidas ou Captcha errado"
            print(f"❌ [{hora}] Login falhou: {txt_erro}")
            status_info["resultado"] = "❌ Login Falhou"
            return False
            
    except Exception as e:
        print(f"💥 [{hora}] Exceção no login: {e}")
        return False

def verificar_e_aceitar_servico():
    """Navega até serviços, acha o primeiro disponível e aceita"""
    hora = time.strftime("%H:%M:%S")
    
    # Garante que estamos logados
    if not fazer_login():
        return False

    try:
        print(f"🔍 [{hora}] Buscando serviços disponíveis...")
        url_servicos = f"{BASE}/index.php?option=com_inscricao&view=servicos"
        resp_serv = SESSAO.get(url_servicos, timeout=15)
        soup = BeautifulSoup(resp_serv.text, 'html.parser')

        # Procura por links de inscrição/aceite
        # Padrão comum: <a href="...task=servico.inscrever&id=XX">
        links_servicos = soup.find_all('a', href=True)
        
        servico_aceito = False
        
        for link in links_servicos:
            href = link['href']
            # Verifica se é um link de ação de serviço
            if 'servico.inscrever' in href or 'servico.aceitar' in href:
                match_id = re.search(r'id=(\d+)', href)
                if match_id:
                    id_serv = match_id.group(1)
                    nome_serv = link.get_text(strip=True) or "Serviço Disponível"
                    
                    print(f"🎯 [{hora}] Serviço encontrado! ID: {id_serv} | Nome: {nome_serv}")
                    
                    # EXECUTA A ACEITAÇÃO
                    url_acao = f"{BASE}/index.php?option=com_inscricao&task=servico.inscrever&id={id_serv}"
                    print(f"⚡ [{hora}] Enviando requisição de aceite...")
                    
                    resp_acao = SESSAO.get(url_acao, timeout=15)
                    
                    # Validação simples de sucesso
                    if resp_acao.status_code == 200:
                        # Verifica se não voltou página de erro
                        if "erro" not in resp_acao.text.lower() and "falha" not in resp_acao.text.lower():
                            msg_final = f"✅ <b>SERVIÇO ACEITO AUTOMATICAMENTE!</b>\n\n📋 <b>{nome_serv}</b>\n🆔 ID: <code>{id_serv}</code>\n⏰ {hora}"
                            print(f"🚀 [{hora}] SUCESSO! Serviço aceito.")
                            avisar_telegram(msg_final)
                            status_info["resultado"] = f"✅ Aceito: {nome_serv}"
                            servico_aceito = True
                            break # Sai do loop após aceitar o primeiro
                        else:
                            print(f"⚠️ [{hora}] O site retornou erro ao aceitar.")
                    else:
                        print(f"❌ [{hora}] Erro HTTP {resp_acao.status_code} ao aceitar.")

        if not servico_aceito:
            print(f"⚠️ [{hora}] Nenhum serviço disponível para aceitar neste momento.")
            status_info["resultado"] = "⚠️ Aguardando vaga"
            
    except Exception as e:
        print(f"💥 [{hora}] Erro ao verificar serviços: {e}")
        status_info["resultado"] = "💥 Erro na busca"

def loop_principal():
    print("🚀 Bot iniciado! Monitorando a cada 60 segundos...")
    avisar_telegram("🚀 <b>Bot PROEISBM Iniciado</b>\nMonitorando serviços a cada 1 minuto.")
    
    while True:
        try:
            verificar_e_aceitar_servico()
            print("💤 Aguardando 60 segundos para próxima verificação...\n")
            time.sleep(60)
        except KeyboardInterrupt:
            print("🛑 Bot parado pelo usuário.")
            break
        except Exception as e:
            print(f"💥 Erro crítico no loop: {e}")
            time.sleep(60)

if __name__ == "__main__":
    # Inicia servidor de saúde em background
    threading.Thread(target=start_health_server, daemon=True).start()
    # Inicia o bot
    loop_principal()
