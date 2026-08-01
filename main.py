import os
import sys
import requests
import time
import re
import threading
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler
from PIL import Image, ImageEnhance, ImageFilter
from io import BytesIO
import pytesseract
from bs4 import BeautifulSoup

# Configuração de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Força saída imediata
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(line_buffering=True)

# --- CONFIGURAÇÕES ---
LOGIN_ID = os.getenv("LOGIN_ID")
SENHA = os.getenv("SENHA")
TG_TOKEN = os.getenv("TG_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")

if not all([LOGIN_ID, SENHA, TG_TOKEN, TG_CHAT_ID]):
    logger.error("❌ ERRO: Variáveis de ambiente faltando.")
    sys.exit(1)

BASE = "http://www.proeisbm.cbmerj.rj.gov.br"
LOGIN_URL = f"{BASE}/index.php?option=com_inscricao&Itemid=82"

status_info = {"resultado": "Iniciando..."}

# Configura Tesseract
try:
    pytesseract.pytesseract.tesseract_cmd = '/usr/bin/tesseract'
except:
    pass

# --- SERVIDOR DE SAÚDE ---
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")
    
    def log_message(self, *args): 
        pass

def start_health_server():
    port = int(os.environ.get('PORT', 8080))
    server = HTTPServer(('0.0.0.0', port), HealthHandler)
    logger.info(f"🖥️ Servidor saúde porta {port}")
    server.serve_forever()

SESSAO = requests.Session()
SESSAO.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
})

# --- OCR MELHORADO ---
def resolver_captcha_real():
    """Baixa e resolve o captcha"""
    try:
        timestamp = int(time.time() * 1000)
        url_captcha = f"{BASE}/captcha2.php?t={timestamp}"
        
        resp = SESSAO.get(url_captcha, timeout=10)
        if resp.status_code != 200:
            return ""
        
        img = Image.open(BytesIO(resp.content))
        
        # Processamento da imagem
        img = img.convert('L')
        img = img.filter(ImageFilter.MedianFilter(size=3))
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(2.5)
        img = img.point(lambda x: 0 if x < 140 else 255, '1')
        
        # OCR com diferentes configurações
        configs = [
            '--psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789',
            '--psm 8 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
        ]
        
        for config in configs:
            texto = pytesseract.image_to_string(img, config=config).strip().upper()
            clean_text = re.sub(r'[^A-Z0-9]', '', texto)
            
            if len(clean_text) == 4:
                logger.info(f"✅ Captcha: {clean_text}")
                return clean_text
        
        return ""
        
    except Exception as e:
        logger.error(f"Erro OCR: {e}")
        return ""

def get_csrf_token(soup):
    for inp in soup.find_all('input', {'type': 'hidden'}):
        name = inp.get('name', '')
        value = inp.get('value', '')
        if value == '1' and len(name) == 32:
            try:
                int(name, 16)
                return name, value
            except ValueError: 
                continue
    return None, None

def avisar_telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": TG_CHAT_ID, "text": msg, "parse_mode": "HTML"}, timeout=10)
    except Exception as e:
        logger.error(f"Erro Telegram: {e}")

def fazer_login():
    logger.info("🔄 Tentando login...")
    
    try:
        resp_home = SESSAO.get(LOGIN_URL, timeout=15)
        soup = BeautifulSoup(resp_home.text, 'html.parser')
        token_name, token_val = get_csrf_token(soup)
        
        if not token_name:
            logger.error("❌ Token não encontrado")
            return False

        captcha_sol = resolver_captcha_real()
        if not captcha_sol:
            logger.error("❌ Falha no Captcha")
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
            logger.info("✅ Login SUCESSO!")
            status_info["resultado"] = "✅ Logado"
            return True
        else:
            logger.error("❌ Login FALHOU")
            return False
            
    except Exception as e:
        logger.error(f"Erro Login: {e}")
        return False

def verificar_e_aceitar():
    if not fazer_login():
        return

    try:
        logger.info("🔍 Buscando serviços...")
        url_servicos = f"{BASE}/index.php?option=com_inscricao&view=servicos"
        resp = SESSAO.get(url_servicos, timeout=20)
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
                    
                    logger.info(f"🎯 VAGA: ID {id_serv} - {nome}")
                    
                    url_acao = f"{BASE}/index.php?option=com_inscricao&task=servico.inscrever&id={id_serv}"
                    resp_acao = SESSAO.get(url_acao, timeout=15)
                    
                    if "erro" not in resp_acao.text.lower():
                        msg = f"✅ SERVIÇO ACEITO!\n📋 {nome}\n🆔 {id_serv}"
                        logger.info(f"🚀 SUCESSO!")
                        avisar_telegram(msg)
                        status_info["resultado"] = "✅ ACEITO"
                        aceito = True
                        break

        if not aceito:
            logger.info("⚠️ Sem vagas")
            status_info["resultado"] = "⚠️ Vazio"

    except Exception as e:
        logger.error(f"Erro busca: {e}")

def loop():
    logger.info("🚀 Bot Iniciado")
    avisar_telegram("🚀 Bot Iniciado")
    
    while True:
        try:
            verificar_e_aceitar()
            logger.info("💤 Dormindo 60s...\n")
            time.sleep(60)
        except Exception as e:
            logger.error(f"Crash: {e}")
            time.sleep(60)

if __name__ == "__main__":
    threading.Thread(target=start_health_server, daemon=True).start()
    loop()