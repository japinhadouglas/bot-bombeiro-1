import os
import sys
import requests
import time
import re
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from PIL import Image, ImageFilter, ImageOps
from io import BytesIO
import pytesseract
from bs4 import BeautifulSoup

# Força saída imediata no Railway
sys.stdout.reconfigure(line_buffering=True)

# --- CONFIGURAÇÕES ---
LOGIN_ID = os.getenv("LOGIN_ID")
SENHA = os.getenv("SENHA")
TG_TOKEN = os.getenv("TG_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")

if not all([LOGIN_ID, SENHA, TG_TOKEN, TG_CHAT_ID]):
    print("❌ ERRO CRÍTICO: Variáveis de ambiente faltando.")
    sys.exit(1)

BASE = "http://www.proeisbm.cbmerj.rj.gov.br"
LOGIN_URL = f"{BASE}/index.php?option=com_inscricao&Itemid=82"

status_info = {"resultado": "Iniciando..."}

# --- SERVIDOR DE SAÚDE ---
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
    print(f"🖥️ Servidor saúde porta {port}")
    server.serve_forever()

SESSAO = requests.Session()
SESSAO.headers.update({'User-Agent': 'Mozilla/5.0'})

# --- OCR ROBUSTO ---
def resolver_captcha_real():
    """Baixa, limpa a imagem e lê o captcha"""
    try:
        url_captcha = f"{BASE}/captcha2.php?t={int(time.time())}"
        resp = SESSAO.get(url_captcha, stream=True, timeout=10)
        
        if resp.status_code != 200: return ""
        
        img = Image.open(BytesIO(resp.content))
        
        # 1. Converter para Escala de Cinza
        img = img.convert('L')
        
        # 2. Aumentar contraste e binarizar (Preto e Branco puro)
        # Isso remove o fundo cinza e deixa apenas as letras nítidas
        threshold = 140
        table = []
        for i in range(256):
            if i < threshold:
                table.append(0)
            else:
                table.append(1)
        img = img.point(table, '1')
        
        # 3. Ler com configuração estrita
        texto = pytesseract.image_to_string(
            img, 
            config='--psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
        ).strip().upper()
        
        # 4. Limpeza final
        clean_text = re.sub(r'[^A-Z0-9]', '', texto)
        
        print(f"🔍 OCR Bruto: '{texto}' | Limpo: '{clean_text}'")
        
        if len(clean_text) == 4:
            return clean_text
        else:
            print(f"⚠️ Captcha inválido ({len(clean_text)} chars): {clean_text}")
            return ""
            
    except Exception as e:
        print(f"💥 Erro OCR: {e}")
        return ""

def get_csrf_token(soup):
    for inp in soup.find_all('input', {'type': 'hidden'}):
        name = inp.get('name', '')
        value = inp.get('value', '')
        if value == '1' and len(name) == 32:
            try:
                int(name, 16)
                return name, value
            except ValueError: continue
    return None, None

def avisar_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
        r = requests.post(url, data={"chat_id": TG_CHAT_ID, "text": msg, "parse_mode": "HTML"}, timeout=10)
        if r.status_code == 200:
            print("📩 Telegram enviado.")
        else:
            print(f"❌ Erro Telegram: {r.text}")
    except Exception as e:
        print(f"💥 Erro Telegram: {e}")

def fazer_login():
    hora = time.strftime("%H:%M:%S")
    print(f"🔄 [{hora}] Tentando login...")
    
    try:
        resp_home = SESSAO.get(LOGIN_URL, timeout=15)
        soup = BeautifulSoup(resp_home.text, 'html.parser')
        token_name, token_val = get_csrf_token(soup)
        
        if not token_name:
            print("❌ Token não encontrado.")
            return False

        captcha_sol = resolver_captcha_real()
        if not captcha_sol:
            print("❌ Falha no Captcha (tentando próximo ciclo...)")
            return False

        dados = {
            "username": LOGIN_ID,
            "passwd": SENHA,
            "cd": captcha_sol,
            "option": "com_user",
            "task": "login",
            "return": "L2luZGV4LnBocD9vcHRpb249Y29tX2xvZ2luJkl0ZW1pZD05Mw==",
            token_name: token_val
        }
        
        resp_post = SESSAO.post(LOGIN_URL, data=dados, timeout=15)
        
        if "logout" in resp_post.text.lower():
            print(f"✅ [{hora}] Login SUCESSO!")
            status_info["resultado"] = "✅ Logado"
            return True
        else:
            print(f"❌ [{hora}] Login FALHOU. Verifique senha/captcha.")
            # Salva o HTML de erro para debug se necessário
            # with open('erro_login.html', 'w') as f: f.write(resp_post.text)
            return False
            
    except Exception as e:
        print(f"💥 Erro Login: {e}")
        return False

def verificar_e_aceitar():
    if not fazer_login(): return

    try:
        print(f"🔍 Buscando serviços...")
        url_servicos = f"{BASE}/index.php?option=com_inscricao&view=servicos"
        resp = SESSAO.get(url_servicos, timeout=15)
        soup = BeautifulSoup(resp.text, 'html.parser')

        links = soup.find_all('a', href=True)
        aceito = False

        for link in links:
            href = link['href']
            if 'servico.inscrever' in href:
                match = re.search(r'id=(\d+)', href)
                if match:
                    id_serv = match.group(1)
                    nome = link.get_text(strip=True)[:40]
                    print(f"🎯 VAGA ENCONTRADA: ID {id_serv} - {nome}")
                    
                    url_acao = f"{BASE}/index.php?option=com_inscricao&task=servico.inscrever&id={id_serv}"
                    resp_acao = SESSAO.get(url_acao, timeout=15)
                    
                    if "erro" not in resp_acao.text.lower():
                        msg = f"✅ <b>SERVIÇO ACEITO!</b>\n📋 {nome}\n🆔 {id_serv}"
                        print(f"🚀 SUCESSO! {msg}")
                        avisar_telegram(msg)
                        status_info["resultado"] = "✅ ACEITO"
                        aceito = True
                        break
                    else:
                        print("⚠️ Erro ao aceitar no site.")

        if not aceito:
            print("⚠️ Sem vagas disponíveis.")
            status_info["resultado"] = "⚠️ Vazio"

    except Exception as e:
        print(f"💥 Erro na busca: {e}")

def loop():
    print("🚀 Bot Iniciado. Ciclo de 60s.")
    avisar_telegram("🚀 Bot Iniciado.")
    while True:
        try:
            verificar_e_aceitar()
            print("💤 Dormindo 60s...\n")
            time.sleep(60)
        except Exception as e:
            print(f"💥 Crash: {e}")
            time.sleep(60)

if __name__ == "__main__":
    threading.Thread(target=start_health_server, daemon=True).start()
    loop()
