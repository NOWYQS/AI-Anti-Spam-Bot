import yaml
from pathlib import Path

class Config:
    _instance = None
    _config = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def _load_config(cls):
        config_path = Path("config.yml")
        if not config_path.exists():
            raise FileNotFoundError("config.yml not found, copy from config.example.yml")
        with open(config_path, "r", encoding="utf-8") as f:
            cls._config = yaml.safe_load(f)

    @classmethod
    def get(cls, key: str, default=None):
        """获取配置项，支持点号分隔的嵌套key，如 'telegram.token'"""
        if cls._config is None:
            cls._load_config()
        
        keys = key.split(".")
        value = cls._config
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return default
        return value if value is not None else default

config = Config()
