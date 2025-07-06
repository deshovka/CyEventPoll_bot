from configparser import ConfigParser

def load_config():
    config = ConfigParser()
    config.read("config.ini")
    return config

def check_access(user_id: int) -> bool:
    config = load_config()
    allowed_ids = [int(id_) for id_ in config["Bot"]["allowed_ids"].split(",")]
    return user_id in allowed_ids