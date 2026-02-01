import json
from pathlib import Path

from confluent_kafka import Consumer, KafkaException
from .result_out_dto import ResultOutDTO
from .result_in_dto import ResultInDTO
from .producer import KafkaProducerClient
from .config import KafkaConfig


class KafkaConsumerClient:
    def __init__(self, cfg: KafkaConfig | None = None):
        self.cfg = cfg or KafkaConfig()
        self.consumer = Consumer({
            "bootstrap.servers": self.cfg.bootstrap_servers,
            "group.id": self.cfg.group_id,
            "enable.auto.commit": False,
        })
        self.consumer.subscribe([self.cfg.topic_in])

        self.producer = KafkaProducerClient(self.cfg)

        print("BOOTSTRAP=", self.cfg.bootstrap_servers, "TOPIC_IN=", self.cfg.topic_in, "GROUP=", self.cfg.group_id)

    def run_forever(self):
        try:
            while True:
                msg = self.consumer.poll(1.0)
                if msg is None:
                    continue
                if msg.error():
                    raise KafkaException(msg.error())

                try:
                    raw = msg.value()
                    if raw is None:
                        raise ValueError("empty message value")

                    d = json.loads(raw.decode("utf-8"))
                    msg_in = ResultInDTO.from_dict(d)

                    ansible_dir = Path("ansible_output")
                    file_list: list[ResultOutDTO] = []

                    if ansible_dir.exists() and ansible_dir.is_dir():
                        for f in ansible_dir.iterdir():
                            if not f.is_file():
                                continue

                            preview = f.read_text(encoding="utf-8", errors="replace")

                            file_list.append(ResultOutDTO(
                                jobid=msg_in.jobid,
                                name=f.name,
                                path=str(f),
                                lang=f.suffix.lstrip("."),
                                preview=preview,
                                size=len(preview),
                            ))

                    self.producer.send(file_list)
                    self.producer.flush()

                    self.consumer.commit(message=msg, asynchronous=False)

                except Exception as e:
                    print(f"handler failed: {e}")

        finally:
            self.consumer.close()
