The Universal Utility Orchestrator is an autonomous orchestration layer to sequence agents to achieve a goal. It is designed to be flexible and adaptable, allowing it to work with a wide range of agents and tasks. 

## Run Locally
To run the Universal Utility Orchestrator locally, follow these steps:

1. Download Ollama Locally on your machine and pull the image:
```bash
ollama pull llama3.1:8b
```
2. Navigate to the project directory:
```bash
cd UniversalUtilityAgent
```
3. Run run_dev.sh:
```bash
chmod +x run_dev.sh
./run_dev.sh
```
4. Once in interactive mode within docker, cd into project directorty and run orchestrator.py:
```bash
cd UniversalUtilityAgent/src/core
python3 orchestrator.py
```