import json
from dataclasses import dataclass

@dataclass
class Config:
    token: str
    max_text_length: int
    min_text_length: int
    max_queue_size: int
    path_default_sempl_voice: str

def load_config(path: str = 'config.json') -> Config:
    with open(path) as f:
        data = json.load(f)
    return Config(**data) 