import secrets

def query_number(text: str, default: int = None) -> int:
    while True:
        try:
            raw: str = input(text)

            if (raw == ""):
                return default

            return int(raw)
        except:
            print("Это не число")

def get_or_default(text: str, default: str = None) -> str:
    value: str = input(text)

    return default if value == "" else value

print(f"""
                                                                                                                                                    
                                                                                  
██ ▄█▀ ▄▄ ▄▄▄▄▄▄ ▄▄▄▄▄▄ ▄▄▄▄▄ ▄▄  ▄▄ █████▄ ▄▄▄▄   ▄▄▄  ▄▄ ▄▄ ▄▄ ▄▄   ▄▄▄▄  ▄▄ ▄▄ 
████   ██   ██     ██   ██▄▄  ███▄██ ██▄▄█▀ ██▄█▄ ██▀██ ▀█▄█▀ ▀███▀   ██▄█▀ ▀███▀  (init.py)
██ ▀█▄ ██   ██     ██   ██▄▄▄ ██ ▀██ ██     ██ ██ ▀███▀ ██ ██   █   ▄ ██      █   
                                                                                  \n\n""")

print("Привет! Это помощник для конфигурации KittenProxy\n")

cookies: str = input("Укажи куки для серверного аккаунта (в Netscape формате!): ")
server_auth_token: str = input("Укажи ключ авторизации для звонков для серверного аккаунта: ")
client_auth_token: str = get_or_default("Укажи ключ авторизации для звонков для клиента (если нужен только сервер - оставь пустым): ", default = "")
target_dc: str = get_or_default("Укажи название DC (если не знаешь что это - оставь пустым, будет использоваться DC \"kittenserver\"): ", "kittenserver")
user_id: int = query_number("Укажи айди пользователя аккаунта на котором будет стоять сервер (куда будет звонить клиент): ")

proxy_host: str = get_or_default("Укажи IP для прокси (если нужен только сервер или не знаешь что это такое - оставь пустым): ", default = "127.0.0.1")
proxy_port: int = query_number("Укажи порт для прокси (если нужен только сервер или не знаешь что это такое - оставь пустым): ", default = 1337)

aes_secret_key: str = secrets.token_hex(32)

config_data: str = f"""

# auto generated config file

VK_COOKIES: str = "{cookies}"
SERVER_CALL_AUTH_TOKEN: str = "{server_auth_token}"
CLIENT_CALL_AUTH_TOKEN: str = "{client_auth_token}"
TARGET_DATACHANNEL: str = "{target_dc}"
TARGET_BOT_USER_ID: int = {user_id}
AES_SECRET_KEY: str = "{aes_secret_key}"
PROXY_CONF: dict = {{
    "host": "{proxy_host}",
    "port": {proxy_port}
}}

"""

with open("config.py", "w", encoding = "utf-8") as f:
    f.write(config_data)

print("Отлично! Твой конфиг сохранен. Можешь запускать сервер/ клиент")
print(f"AES Secret Key: \"{aes_secret_key}\" (используй его в клиенте)")