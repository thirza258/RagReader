class PromptBuilder:
    def __init__(self, system_prompt: str, prompt_template: str):
        self.system_prompt = system_prompt
        self.prompt_template = prompt_template

    def agentic_prompt(self) -> str:
        return f"""
        
        """

    def dense_rag(self) -> str:
        return f"""
        
        """

    def sparse_rag(self) -> str:
        return f"""
        """

    def graph_rag(self) -> str:
        return f"""
        """
    
    def hybrid_rag(self) -> str:
        return f"""
        """
        
        