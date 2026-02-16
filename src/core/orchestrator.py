import json
import yaml
import requests
from langchain_ollama import ChatOllama
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage

class UniversalOrchestrator:
    def __init__(self, registry_path = "agents.json", config_path = "config.yaml"):
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)
        with open(registry_path, 'r') as f:
            self.registry = json.load(f)["agents"]

        self.model = ChatOllama(
            model = self.config["llm"]["model"],
            base_url = self.config["llm"]["base_url"],
            temperature = self.config["llm"]["temperature"]
        )
    
    def get_system_message(self):
        agents_available = "\n".join([f"- {a['name']}: {a['description']}" for a in self.registry])
        return f"""
        You are the Universal Orchestrator, an autonomous agent designed to sequence and manage other agents to achieve complex goals. 
        Your goal is to solve user queries by calling specializaed agents available here:
        {agents_available}

        If you use an agent, respond ONLY with the agent name.
        Do not attempt to solve the problem yourself if an agent is available. Always use agents when possible. Do not answer general trivial questions yourself, you are specialized
        in orchestrating agents, not in answering questions. If you don't know the answer to a question, find an agent that does.
        If you have enough information to answer the user's query, respond with 'FINAL_ANSWER: [your response]'.
        """
    
    def run(self, user_query):
        messages = [
            SystemMessage(content=self.get_system_message()),
            HumanMessage(content=user_query)
        ]

        for i in range(self.config["orchestration"]["max_iterations"]):
            print(f"[Hub] Thinking (Iteration {i+1})...")
            response = self.model.invoke(messages).content.strip()

            if "FINAL_ANSWER:" in response:
                return response.split("FINAL_ANSWER:")[-1].strip()
            
            agent = next((a for a in self.registry if a["name"] in response), None)

            if agent:
                print(f"[Hub] Activating Agent: {agent['name']}...")
                #TODO: Implement actual agent calling logic here. For now, we will mock the agent response.
                agent_result = f"MOCK_RESULT: Successfully processed data for {agent['name']}."
                messages.append(SystemMessage(content=f"Result from {agent['name']}: {agent_result}"))
            else:
                # Fallback if Ollama hallucinates an agent name
                messages.append(SystemMessage(content="That agent does not exist. Please choose from the list provided."))

# Quick Test
if __name__ == "__main__":
    hub = UniversalOrchestrator()
    print(hub.run("I think my bill is too high this month, can you check it?"))