from langchain_openai import ChatOpenAI

class LLM:
    def __init__(self, model: str, temperature: float = 0.0):
        self.model = model
        self.temperature = temperature

    def generate(self, prompt: str) -> str:
        llm = ChatOpenAI(model=self.model, temperature=self.temperature)
        return llm.invoke(prompt)