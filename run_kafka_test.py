from src.messaging.consumer import KafkaConsumerClient

if __name__ == "__main__":
    KafkaConsumerClient().run_forever()
