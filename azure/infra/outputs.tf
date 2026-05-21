
output "resource_group_name" {
  description = "Resource group containing all project resources"
  value       = module.resource_group.name
}

output "key_vault_name" {
  description = "Key Vault name"
  value       = module.key_vault.vault_name
}

output "key_vault_uri" {
  description = "Key Vault URI"
  value       = module.key_vault.vault_uri
}

output "cosmos_account_name" {
  description = "Cosmos DB account name (used in az cli queries)"
  value       = module.cosmos_db.account_name
}

output "cosmos_endpoint" {
  description = "Cosmos DB account endpoint URL"
  value       = module.cosmos_db.endpoint
  sensitive   = true
}

output "cosmos_database_name" {
  description = "Cosmos DB database name"
  value       = module.cosmos_db.database_name
}

output "orchestrator_app_name" {
  description = "Orchestrator Function App name"
  value       = module.orchestrator.function_app_name
}

output "orchestrator_url" {
  description = "Orchestrator base URL"
  value       = "https://${module.orchestrator.default_hostname}"
}

output "orchestrator_chat_endpoint" {
  description = "Orchestrator /api/chat endpoint (append ?code=<key>)"
  value       = "https://${module.orchestrator.default_hostname}/api/chat"
}

output "openai_endpoint" {
  description = "Azure OpenAI endpoint URL"
  value       = module.openai.endpoint
}

output "registry_app_name" {
  description = "Registry Function App name"
  value       = module.registry.function_app_name
}

output "registry_url" {
  description = "Registry API base URL"
  value       = "https://${module.registry.default_hostname}"
}

output "registry_health_endpoint" {
  description = "Registry health check (no key required)"
  value       = "https://${module.registry.default_hostname}/api/health"
}

output "registry_agents_endpoint" {
  description = "Registry agents list endpoint (append ?code=<key>)"
  value       = "https://${module.registry.default_hostname}/api/agents"
}

output "registry_dashboard_url" {
  description = "Registry HTML dashboard (no key required)"
  value       = "https://${module.registry.default_hostname}/api/agents/dashboard"
}

output "swa_name" {
  description = "Static Web App resource name"
  value       = module.swa.id
}

output "swa_url" {
  description = "Registry UI live URL"
  value       = module.swa.url
}

output "swa_deployment_token" {
  description = "SWA deployment token — also stored in Key Vault as swa-deployment-token"
  value       = module.swa.deployment_token
  sensitive   = true
}

output "shell_exports" {
  description = "Copy-paste into terminal to set all session variables"
  value       = <<-EOT
    export RG_NAME="${module.resource_group.name}"
    export COSMOS_ACCOUNT="${module.cosmos_db.account_name}"
    export COSMOS_DB="${module.cosmos_db.database_name}"
    export KV_NAME="${module.key_vault.vault_name}"
    export KV_URL="${module.key_vault.vault_uri}"
    export FUNC_APP_NAME="${module.orchestrator.function_app_name}"
    export FUNC_URL="https://${module.orchestrator.default_hostname}"
    export REGISTRY_APP_NAME="${module.registry.function_app_name}"
    export REGISTRY_URL="https://${module.registry.default_hostname}"
    export SWA_NAME="${module.swa.id}"
    export SWA_URL="${module.swa.url}"
  EOT
}
