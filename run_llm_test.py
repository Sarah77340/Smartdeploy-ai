from src.engine.llm.ollama_openai import OllamaProvider, OllamaConfig

llm = OllamaProvider(OllamaConfig(model="mistral"))

out = llm.chat_json([
    {"role": "system", "content": "Reply ONLY with valid JSON. No markdown. No extra text."},
    {"role": "user", "content": "Return exactly {\"ping\": \"pong\"}."},
])

print(out)
