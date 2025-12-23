from common.prompt_builder import PromptBuilder
from ai_handler.llm import LLM

llm = LLM(model="gpt-4o-mini", temperature=0.0)
prompt_builder = PromptBuilder(system_prompt="You are a helpful assistant.", prompt_template="You are a helpful assistant.")


class ChatSystem:
    def __init__(
        self,
        ai_handler,
        retriever=None,
        memory=None,
        prompt_builder=None
    ):
        self.ai_handler = ai_handler
        self.retriever = retriever
        self.memory = memory
        self.prompt_builder = prompt_builder

    def chat(self, user_message: str, user_id: str = None):
        """
        Main entry point for chat system
        """

        conversation = []
        if self.memory and user_id:
            conversation = self.memory.load(user_id)

        context = ""
        if self.retriever:
            docs = self.retriever.retrieve(user_message)
            context = "\n".join([doc.content for doc in docs])

        # 3. Build prompt
        if self.prompt_builder:
            final_prompt = self.prompt_builder.build(
                message=user_message,
                context=context,
                history=conversation
            )
        else:
            final_prompt = f"""
            Context:
            {context}

            History:
            {conversation}

            User: {user_message}
            Assistant:
            """

        response = self.ai_handler.generate(final_prompt)

        if self.memory and user_id:
            self.memory.save(user_id, user_message, response)

        return {
            "answer": response,
            "context": context
        }