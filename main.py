import os
import requests
import time
import re
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from PIL import Image
from io import BytesIO
import pytesseract
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

# --- CONFIGURAÇÕES (RAILWAY SECRETS) ---
LOGIN_ID = os.getenv("LOGIN_ID")
SENHA = os.getenv("SENHA")
TG_TOKEN = os.getenv("TG_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")

BASE = "http://www.proeisbm.cbmerj.rj.gov.br"
LOGIN_URL = f"{BASE}/index.php?option=com_inscricao&Itemid=82"

status_info = {"ultima_verificacao": "Aguardando...", "resultado": "Iniciando"}

# --- SERVIDOR DE SAÚDE (Obrigatório para Railway) ---
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        html = f"""<!DOCTYPE html><html><body>
        <h1>🤖 Bot PROEISBM Ativo</h1>
        <p>Status: {status_info['resultado']}</p>
        </body></html>"""
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(html.encode())
    def log_message(self, *args): pass

def start_health_server():
    port = int(os.environ.get('PORT', 8080))
    server = HTTPServer(('0.0.0.0', port), HealthHandler)
    server.serve_forever()

# --- SESSÃO HTTP ---
SESSAO = requests.Session()
SESSAO.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})

# --- FUNÇÕES AUXILIARES ---
def resolver_captcha():
    try:
        img_data = SESSAO.get(f"{BASE}/captcha2.php?t={time.time()}", stream=True, timeout=10).content
        img = Image.open(BytesIO(img_data))
        # Configuração agressiva para ler apenas letras/números
        texto = pytesseract.image_to_string(img, config='--psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789').strip()
        return texto[:4] if len(texto) >= 4 else ""
    except Exception as e:
        print(f"❌ Erro OCR: {e}")
        return ""

def get_csrf_token(soup):
    for inp in soup.find_all('input', {'type': 'hidden'}):
        name = inp.get('name', '')
        value = inp.get('value', '')
        if value == '1' and re.match(r'^[a-f0-9]{32}

### **🔧 O que este código faz diferente:**

1. **Busca Ativa:** Ele não só lê, mas procura especificamente por links contendo `servico.inscrever` ou `aceitar` no HTML.

2. **Execução:** Ao encontrar o ID, ele dispara uma requisição `GET` para a URL de ação (`task=servico.inscrever&id=XYZ`).

3. **Validação:** Verifica se a resposta não contém palavras como "erro" ou "falha" para confirmar o sucesso.

### **⚠️ Importante:**
Se o site usar **POST** em vez de **GET** para aceitar, ou se tiver um **token CSRF** específico na página de serviços, o código acima pode precisar de um pequeno ajuste.
* **Teste manual:** Entre no site, clique em "Aceitar" e veja na aba "Network" do navegador se a requisição é `GET` ou `POST`.
* Se for `POST`, me avise que eu altero a função `tentar_aceitar_servico` para enviar um formulário.

Por enquanto, tente rodar este. Se falhar, me mande o log do Railway dizendo "Erro HTTP..." ou "Ação retornou erro"., name):
            return name, value
    return None, None

def avisar(msg):
    try:
        url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": TG_CHAT_ID, "text": msg, "parse_mode": "HTML"}, timeout=10)
    except: pass

def login_automatico():
    hora = time.strftime("%H:%M:%S")
    try:
        resp = SESSAO.get(LOGIN_URL, timeout=15)
        soup = BeautifulSoup(resp.text, 'html.parser')
        token_name, token_value = get_csrf_token(soup)
        
        if not token_name: return False

        captcha = resolver_captcha()
        if len(captcha) != 4: 
            print(f"⚠️ Captcha inválido: '{captcha}'")
            return False

        dados = {
            "username": LOGIN_ID,
            "passwd": SENHA,
            "cd": captcha,
            "option": "com_user",
            "task": "login",
            "return": "L2luZGV4LnBocD9vcHRpb249Y29tX2xvZ2luJkl0ZW1pZD05Mw==",
            token_name: token_value,
        }
        
        resp_login = SESSAO.post(LOGIN_URL, data=dados, timeout=15)
        
        # Verifica se logou com sucesso procurando por elementos de logout
        if "logout" in resp_login.text.lower() or "sair" in resp_login.text.lower():
            print(f"✅ [{hora}] Logado.")
            status_info["resultado"] = "✅ Logado"
            return True
        else:
            print(f"❌ [{hora}] Falha no login.")
            status_info["resultado"] = "❌ Login Falhou"
            return False
    except Exception as e:
        print(f"💥 Erro login: {e}")
        return False

def tentar_aceitar_servico():
    """
    Lê a página de serviços, encontra o primeiro disponível e tenta aceitar.
    """
    hora = time.strftime("%H:%M:%S")
    
    # 1. Garante login
    if not login_automatico():
        return False

    try:
        # 2. Acessa a página de serviços
        url_servicos = f"{BASE}/index.php?option=com_inscricao&view=servicos"
        resp_serv = SESSAO.get(url_servicos, timeout=15)
        soup = BeautifulSoup(resp_serv.text, 'html.parser')

        # 3. Procura linhas de serviço (Ajuste o seletor conforme o HTML real)
        # Geralmente é uma tabela <table> com <tr>
        linhas = soup.find_all('tr')
        
        servico_encontrado = False
        id_servico = None
        nome_servico = "Desconhecido"

        for tr in linhas:
            # Procura por texto que indique disponibilidade ou botão de inscrição
            # Exemplo: procura por links com 'task=servico.inscrever' ou similar
            links = tr.find_all('a', href=True)
            for link in links:
                href = link['href']
                # Padrão comum Joomla: option=com_inscricao&task=servico.inscrever&id=XX
                if 'servico.inscrever' in href or 'aceitar' in href.lower():
                    match = re.search(r'id=(\d+)', href)
                    if match:
                        id_servico = match.group(1)
                        nome_servico = tr.get_text(strip=True)[:50]
                        servico_encontrado = True
                        break
            if servico_encontrado: break

        # Se não achou pelo link, tenta achar por classe específica se existir
        if not servico_encontrado:
             # Tenta achar botões com classes comuns
             botoes = soup.find_all('button', class_=lambda c: c and 'btn' in c.lower())
             for btn in botoes:
                 if 'inscrever' in btn.get_text().lower() or 'aceitar' in btn.get_text().lower():
                     # Muitas vezes o ID está num input hidden próximo ou no onclick
                     # Isso depende muito do HTML específico. Vamos assumir que o link acima funciona primeiro.
                     pass 

        if servico_encontrado and id_servico:
            print(f"🎯 [{hora}] Serviço encontrado: ID {id_servico} - {nome_servico}")
            
            # 4. EXECUTA A ACEITAÇÃO
            # Constrói a URL de ação. Pode ser GET ou POST dependendo do site.
            # Tenta GET primeiro (mais comum em links diretos)
            url_acao = f"{BASE}/index.php?option=com_inscricao&task=servico.inscrever&id={id_servico}"
            
            # Se o site usar CSRF na ação, precisaria pegar o token novamente, 
            # mas muitas vezes o link direto já valida a sessão.
            resp_acao = SESSAO.get(url_acao, timeout=15)
            
            # Verifica se deu certo (redirecionamento ou mensagem de sucesso)
            if resp_acao.status_code == 200:
                # Verifica se há mensagem de erro na resposta
                if "erro" not in resp_acao.text.lower() and "falha" not in resp_acao.text.lower():
                    msg_sucesso = f"✅ <b>SERVIÇO ACEITO AUTOMATICAMENTE!</b>\n📋 {nome_servico}\n🆔 ID: {id_servico}\n⏰ {hora}"
                    print(f"🚀 SUCESSO: {msg_sucesso}")
                    avisar(msg_sucesso)
                    status_info["resultado"] = f"✅ Aceito: {nome_servico}"
                    return True
                else:
                    print(f"⚠️ [{hora}] Ação retornou erro na página.")
            else:
                print(f"❌ [{hora}] Erro HTTP ao aceitar: {resp_acao.status_code}")
        
        else:
            print(f"⚠️ [{hora}] Nenhum serviço disponível para aceitar.")
            status_info["resultado"] = "⚠️ Vazio"
            return False

    except Exception as e:
        print(f"💥 [{hora}] Erro ao processar serviços: {e}")
        status_info["resultado"] = "💥 Erro Processo"
        return False

def bot_loop():
    print("🚀 Bot iniciado. Monitorando...")
    avisar("🚀 Bot PROEISBM iniciado.")
    while True:
        try:
            if tentar_aceitar_servico():
                # Se aceitou, espera um tempo maior para não spammar
                time.sleep(300)
            else:
                # Se não achou, verifica rápido
                time.sleep(60)
        except Exception as e:
            print(f"💥 Erro no loop principal: {e}")
            time.sleep(60)

if __name__ == "__main__":
    threading.Thread(target=start_health_server, daemon=True).start()
    bot_loop()
