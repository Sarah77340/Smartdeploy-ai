from confluent_kafka import Producer
import json
from .config import KafkaConfig


class KafkaProducerClient:
    def __init__(self, cfg: KafkaConfig | None = None):
        self.cfg = cfg or KafkaConfig()
        self.producer = Producer({
            "bootstrap.servers": self.cfg.bootstrap_servers,
            "acks": "all",
            "enable.idempotence": True,
            "retries": 5,
        })

    def send(self, payload: list) -> None:
        value = json.dumps([x.to_dict() for x in payload], ensure_ascii=False)
        self.producer.produce(self.cfg.topic_out, value=value)
        self.producer.poll(0)

    def flush(self) -> None:
        self.producer.flush()
