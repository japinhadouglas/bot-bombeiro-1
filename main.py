import os
import sys
import requests
import time
import re
import threading
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler
from PIL import Image, ImageEnhance, ImageFilter, ImageOps
from io import BytesIO
import pytesseract
from bs4 import BeautifulSoup

# Configuração de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Força saída imediata no Railway
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(line_buffering=True)

# --- CONFIGURAÇÕES ---
LOGIN_ID = os.getenv("LOGIN_ID")
SENHA = os.getenv("SENHA")
TG_TOKEN = os.getenv("TG_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")

if not all([LOGIN_ID, SENHA, TG_TOKEN, TG_CHAT_ID]):
    logger.error("❌ ERRO CRÍTICO: Variáveis de ambiente faltando.")
    sys.exit(1)

BASE = "http://www.proeisbm.cbmerj.rj.gov.br"
LOGIN_URL = f"{BASE}/index.php?option=com_inscricao&Itemid=82"

status_info = {
    "resultado": "Iniciando...",
    "ultimo_login": "Nunca",
    "ultimo_servico": "Nenhum",
    "total_verificacoes": 0,
    "uptime": 0
}

# Configuração do Tesseract
try:
    pytesseract.pytesseract.tesseract_cmd = '/usr/bin/tesseract'
    logger.info("✅ Tesseract configurado")
except Exception as e:
    logger.error(f"❌ Erro ao configurar Tesseract: {e}")

# --- SERVIDOR DE SAÚDE ---
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            
            import json
            response = {
                "status": "healthy",
                "info": status_info,
                "timestamp": time.time()
            }
            self.wfile.write(json.dumps(response).encode())
        except Exception as e:
            logger.error(f"Erro no healthcheck: {e}")

    def log_message(self, *args): 
        pass

def start_health_server():
    port = int(os.environ.get('PORT', 8080))
    try:
        server = HTTPServer(('0.0.0.0', port), HealthHandler)
        logger.info(f"🖥️ Servidor saúde porta {port}")
        server.serve_forever()
    except Exception as e:
        logger.error(f"❌ Erro servidor saúde: {e}")

SESSAO = requests.Session()
SESSAO.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'pt-BR,pt;q=0.9,en;q=0.8',
    'Connection': 'keep-alive'
})

start_time = time.time()

def resolver_captcha_real(max_tentativas=5):
    """Baixa e resolve o captcha com múltiplas técnicas"""
    for tentativa in range(max_tentativas):
        try:
            timestamp = int(time.time() * 1000)
            url_captcha = f"{BASE}/captcha2.php?t={timestamp}"
            
            img_headers = {
                'Referer': LOGIN_URL,
                'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8'
            }
            
            resp = SESSAO.get(url_captcha, headers=img_headers, timeout=10)
            
            if resp.status_code != 200:
                logger.warning(f"Status code captcha: {resp.status_code}")
                continue
            
            # Salva a imagem para debug (opcional)
            # with open(f'captcha_{tentativa}.png', 'wb') as f:
            #     f.write(resp.content)
            
            img = Image.open(BytesIO(resp.content))
            
            # === TÉCNICAS MELHORADAS DE PROCESSAMENTO ===
            
            # 1. Converte para escala de cinza
            img = img.convert('L')
            
            # 2. Aplica filtro para reduzir ruído
            img = img.filter(ImageFilter.MedianFilter(size=3))
            
            # 3. Aumenta contraste
            enhancer = ImageEnhance.Contrast(img)
            img = enhancer.enhance(2.5)
            
            # 4. Aumenta nitidez
            enhancer = ImageEnhance.Sharpness(img)
            img = enhancer.enhance(2.0)
            
            # 5. Binarização adaptativa
            # Tenta diferentes limiares
            limiares = [120, 140, 160, 180]
            
            for limiar in limiares:
                # Cria uma cópia para teste
                img_teste = img.copy()
                
                # Binariza com o limiar atual
                img_teste = img_teste.point(lambda x: 0 if x < limiar else 255, '1')
                
                # Opcional: redimensionar para melhorar OCR
                # img_teste = img_teste.resize((img_teste.width * 2, img_teste.height * 2), Image.Resampling.LANCZOS)
                
                # Tenta diferentes configurações de OCR
                configs = [
                    f'--psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789',
                    f'--psm 8 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789',
                    f'--psm 6 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789',
                    f'--psm 10 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
                ]
                
                for config in configs:
                    texto = pytesseract.image_to_string(img_teste, config=config).strip().upper()
                    # Remove caracteres especiais
                    clean_text = re.sub(r'[^A-Z0-9]', '', texto)
                    
                    # Se encontrou 4 caracteres, retorna
                    if len(clean_text) == 4:
                        logger.info(f"✅ Captcha resolvido (limiar={limiar}): '{clean_text}'")
                        return clean_text
                    
                    # Se encontrou 3 caracteres, pode estar faltando um
                    if len(clean_text) == 3:
                        # Tenta adicionar caracteres comuns que podem estar faltando
                        letras_comuns = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J', 'K', 'L', 'M', 'N', 'O', 'P', 'Q', 'R', 'S', 'T', 'U', 'V', 'W', 'X', 'Y', 'Z']
                        for letra in letras_comuns:
                            for pos in range(4):
                                texto_teste = clean_text[:pos] + letra + clean_text[pos:]
                                if len(texto_teste) == 4:
                                    logger.info(f"🔍 Tentando completar captcha: {texto_teste}")
                                    # Não retorna automaticamente, apenas loga
            
            # Se chegou aqui, tenta uma abordagem mais agressiva
            logger.warning(f"Tentativa {tentativa+1} falhou, tentando novamente...")
            time.sleep(2)
            
        except Exception as e:
            logger.error(f"💥 Erro OCR tentativa {tentativa+1}: {e}")
            time.sleep(2)
    
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
        payload = {
            "chat_id": TG_CHAT_ID, 
            "text": msg, 
            "parse_mode": "HTML"
        }
        r = requests.post(url, data=payload, timeout=10)
        if r.status_code == 200:
            logger.info("📩 Telegram enviado")
        else:
            logger.error(f"❌ Erro Telegram: {r.text}")
    except Exception as e:
        logger.error(f"💥 Erro Telegram: {e}")

def fazer_login():
    hora = time.strftime("%H:%M:%S")
    logger.info(f"🔄 [{hora}] Tentando login...")
    
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
            logger.info(f"✅ [{hora}] Login SUCESSO!")
            status_info["resultado"] = "✅ Logado"
            status_info["ultimo_login"] = hora
            return True
        else:
            logger.error(f"❌ [{hora}] Login FALHOU")
            return False
            
    except Exception as e:
        logger.error(f"💥 Erro Login: {e}")
        return False

def verificar_e_aceitar():
    if not fazer_login():
        return

    try:
        logger.info(f"🔍 Buscando serviços...")
        url_servicos = f"{BASE}/index.php?option=com_inscricao&view=servicos"
        resp = SESSAO.get(url_servicos, timeout=20)
        soup = BeautifulSoup(resp.text, 'html.parser')

        links = soup.find_all('a', href=True)
        aceito = False

        for link in links:
            href = link['href']
            if 'servico.inscrever' in href:
                match = re.search(r'id=(\d+)', href)
                if not match:
                    continue
                    
                id_serv = match.group(1)
                nome = link.get_text(strip=True)[:50]
                
                logger.info(f"🎯 VAGA ENCONTRADA: ID {id_serv} - {nome}")
                
                url_acao = f"{BASE}/index.php?option=com_inscricao&task=servico.inscrever&id={id_serv}"
                resp_acao = SESSAO.get(url_acao, timeout=15)
                
                if "erro" not in resp_acao.text.lower():
                    msg = f"""✅ <b>SERVIÇO ACEITO!</b>
📋 <b>Serviço:</b> {nome}
🆔 <b>ID:</b> {id_serv}
⏰ <b>Horário:</b> {time.strftime('%H:%M:%S %d/%m/%Y')}"""
                    
                    logger.info(f"🚀 SUCESSO! {msg}")
                    avisar_telegram(msg)
                    status_info["resultado"] = "✅ ACEITO"
                    status_info["ultimo_servico"] = nome
                    aceito = True
                    break

        if not aceito:
            logger.info("⚠️ Nenhuma vaga disponível")
            status_info["resultado"] = "⚠️ Aguardando vagas"

    except Exception as e:
        logger.error(f"💥 Erro na busca: {e}")

def loop():
    logger.info("🚀 Bot Iniciado no Railway!")
    avisar_telegram("🚀 Bot iniciado e monitorando vagas no site do CBMERJ!")
    
    while True:
        try:
            status_info["total_verificacoes"] += 1
            status_info["uptime"] = int(time.time() - start_time)
            
            verificar_e_aceitar()
            logger.info(f"💤 Dormindo 60s... (Verificação #{status_info['total_verificacoes']})")
            time.sleep(60)
            
        except Exception as e:
            logger.error(f"💥 Crash no loop: {e}")
            time.sleep(60)

if __name__ == "__main__":
    health_thread = threading.Thread(target=start_health_server, daemon=True)
    health_thread.start()
    loop()