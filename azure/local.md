# Local Development Guide

We use a fully decoupled, emulator-based local development environment. You can run the complete multi-agent orchestrator entirely on your laptop with **no heavy Azure infrastructure footprint**.

## How It Works
- **Cosmos DB Emulator**: A local Docker container mimics Azure Cosmos DB.
- **Azurite**: A local Docker container mimics Azure Blob/Queue/Table Storage.
- **Cosmos Init Job**: A one-shot container auto-creates the required Cosmos database/containers.
- **Python Shims**: When `USE_LOCAL_EMULATORS=true`, auth/secret flows use local-safe behavior:
  - Function HTTP auth defaults to `ANONYMOUS`.
  - Admin login defaults to `admin / password`.
  - Agent auth secrets are stored as inline references (not Key Vault writes).
  - Runtime contract uses `APP_ENV=local` with strict mode disabled.

## 🏃‍♂️ How to Run

1. Ensure your `.env` file (`azure/orchestrator/.env`) contains your real Azure OpenAI configuration. You do not need Key Vault URLs or Tenant IDs.
```bash
# This is all you need for the backend to work!
AZURE_OPENAI_API_KEY=your_real_openai_key
AZURE_OPENAI_ENDPOINT=https://your-instance.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT=gpt-4o
```

2. Boot the stack!
```bash
cd azure
docker-compose up --build
```
> [!NOTE]
> The Cosmos DB emulator can take roughly 30-45 seconds to initialize on its first boot. 
> The `cosmos-init` service may retry while Cosmos starts; this is expected.

## 🖥️ Accessing the Services

- ✨ **Registry UI**: [http://localhost:5173](http://localhost:5173)
  - **Username:** `admin`
  - **Password:** `password`
- ⚙️ **Registry Backend API**: [http://localhost:7072](http://localhost:7072)
- 🧠 **Orchestrator API**: [http://localhost:7071](http://localhost:7071)

## Testing the "Production" Cloud Flow Locally
If you want production-like behavior locally:

1. Set `APP_ENV=prod`.
2. Set `USE_LOCAL_EMULATORS=false`.
3. Set `REGISTRY_HTTP_AUTH_LEVEL=FUNCTION` and `ORCHESTRATOR_HTTP_AUTH_LEVEL=FUNCTION`.
4. Set `REGISTRY_STRICT_MODE=true` and `ORCHESTRATOR_STRICT_MODE=true`.
5. Provide `BUILD_VERSION`, `BUILD_SHA`, and required cloud settings (`KEY_VAULT_URL`, etc.).
6. Provide `VITE_FUNC_CODE` for the UI.
