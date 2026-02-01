import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")


@dataclass(frozen=True)
class KafkaConfig:
    bootstrap_servers: str = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    topic_in: str = os.getenv("KAFKA_TOPIC_IN", "test-topic")
    topic_out: str = os.getenv("KAFKA_TOPIC_OUT", "test-topic")
    group_id: str = os.getenv("KAFKA_GROUP_ID", "demo-group")
